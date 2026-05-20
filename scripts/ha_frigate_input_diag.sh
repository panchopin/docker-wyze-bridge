#!/bin/sh
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)

CAMERAS="${HA_FRIGATE_DIAG_CAMERAS:-}"
FRIGATE_SLUG="${HA_FRIGATE_ADDON_SLUG:-ccab4aaf_frigate}"
SCRYPTED_SLUG="${HA_SCRYPTED_ADDON_SLUG:-09e60fb6_scrypted}"
LINES="${HA_FRIGATE_DIAG_LOG_LINES:-160}"

usage() {
  cat <<EOF
Usage: HA_FRIGATE_DIAG_CAMERAS="south_driveway" scripts/ha_frigate_input_diag.sh

Runs a read-only Home Assistant diagnostic for Frigate/Scrypted RTSP input
health. It prints current Frigate FPS, the named cameras' configured input
paths, Frigate ffprobe results for those exact paths, recent Frigate/Scrypted
log clues, and sanitized add-on state. It does not stop, start, rebuild,
restart, reboot, or edit anything.

Environment:
  HA_FRIGATE_DIAG_CAMERAS    required, space/comma-separated Frigate camera names
  HA_FRIGATE_ADDON_SLUG      default: $FRIGATE_SLUG
  HA_SCRYPTED_ADDON_SLUG     default: $SCRYPTED_SLUG
  HA_FRIGATE_DIAG_LOG_LINES  default: $LINES
EOF
}

case "${1:-}" in
  --help|-h|help)
    usage
    exit 0
    ;;
  "")
    ;;
  *)
    usage >&2
    exit 1
    ;;
esac

validate_slug() {
  name="$1"
  value="$2"
  case "$value" in
    ""|*[!A-Za-z0-9_-]*)
      echo "Invalid $name: only letters, numbers, '_' and '-' are allowed." >&2
      exit 1
      ;;
  esac
}

validate_number() {
  name="$1"
  value="$2"
  case "$value" in
    ""|*[!0-9]*)
      echo "Invalid $name: use a positive integer." >&2
      exit 1
      ;;
    0)
      echo "Invalid $name: use a positive integer." >&2
      exit 1
      ;;
  esac
}

CAMERA_LIST=$(printf '%s' "$CAMERAS" | tr ',' ' ' | xargs)
if [ -z "$CAMERA_LIST" ]; then
  echo "Missing HA_FRIGATE_DIAG_CAMERAS. Name the Frigate camera(s) to diagnose." >&2
  exit 1
fi

for camera in $CAMERA_LIST; do
  case "$camera" in
    ""|*[!A-Za-z0-9_.-]*)
      echo "Invalid camera name '$camera': only letters, numbers, '.', '_' and '-' are allowed." >&2
      exit 1
      ;;
  esac
done

validate_slug "HA_FRIGATE_ADDON_SLUG" "$FRIGATE_SLUG"
validate_slug "HA_SCRYPTED_ADDON_SLUG" "$SCRYPTED_SLUG"
validate_number "HA_FRIGATE_DIAG_LOG_LINES" "$LINES"

"$SCRIPT_DIR/ha_ssh.sh" "HA_FRIGATE_DIAG_CAMERAS='$CAMERA_LIST' HA_FRIGATE_DIAG_SLUG=$FRIGATE_SLUG HA_SCRYPTED_DIAG_SLUG=$SCRYPTED_SLUG HA_FRIGATE_DIAG_LINES=$LINES sh -s" <<'REMOTE'
set -eu

CAMERAS="$HA_FRIGATE_DIAG_CAMERAS"
FRIGATE_SLUG="$HA_FRIGATE_DIAG_SLUG"
SCRYPTED_SLUG="$HA_SCRYPTED_DIAG_SLUG"
LINES="$HA_FRIGATE_DIAG_LINES"

section() {
  printf '\n## %s\n' "$1"
}

redact() {
  sed -E 's/api=[^" ]+/api=<redacted>/g; s#(rtsp://)[^/@[:space:]]+:[^/@[:space:]]+@#\1<redacted>@#g'
}

urlencode() {
  jq -rn --arg v "$1" '$v|@uri'
}

section "Frigate/Scrypted Input Diagnostic"
echo "cameras=$CAMERAS"
echo "frigate_slug=$FRIGATE_SLUG"
echo "scrypted_slug=$SCRYPTED_SLUG"

section "Current Frigate Stats"
STATS=$(curl -fsS --max-time 8 http://ccab4aaf-frigate:5000/api/stats 2>/dev/null || true)
if [ -z "$STATS" ]; then
  echo "<empty>"
else
  printf '%s\n' "$STATS" \
    | jq -r '.cameras | to_entries[] | [.key, .value.camera_fps, .value.process_fps, .value.skipped_fps, (.value.ffmpeg_pid // ""), (.value.capture_pid // "")] | @tsv' \
    | redact
fi

CONFIG=$(curl -fsS --max-time 8 http://ccab4aaf-frigate:5000/api/config 2>/dev/null || true)

for camera in $CAMERAS; do
  section "Camera $camera Config Inputs"
  paths=""
  if [ -z "$CONFIG" ]; then
    echo "<empty config>"
  else
    printf '%s\n' "$CONFIG" \
      | jq -r --arg camera "$camera" '.cameras[$camera].ffmpeg.inputs[]? | .path as $p | (.roles // [])[] as $r | [$r,$p] | @tsv' \
      | redact
    paths=$(printf '%s\n' "$CONFIG" | jq -r --arg camera "$camera" '.cameras[$camera].ffmpeg.inputs[]?.path' 2>/dev/null || true)
  fi

  section "Camera $camera FFprobe"
  if [ -z "$paths" ]; then
    echo "paths=<none>"
  else
    for path in $paths; do
      printf 'path=%s\n' "$path" | redact
      encoded=$(urlencode "$path")
      body=$(curl -fsS --max-time 20 "http://ccab4aaf-frigate:5000/api/ffprobe?paths=$encoded" 2>/dev/null || true)
      if [ -z "$body" ]; then
        echo "ffprobe=<empty>"
      else
        printf '%s\n' "$body" | jq -c . 2>/dev/null | redact || printf '%s\n' "$body" | redact
      fi
    done
  fi

  section "Camera $camera Recent Frigate Logs"
  ha apps logs "$FRIGATE_SLUG" 2>/dev/null \
    | grep -Ei "$camera|Bad Request|Unable to read frames|Ffmpeg process crashed|No new recording segments|skipped" \
    | tail -n "$LINES" \
    | redact || true
done

section "Recent Scrypted RTSP Logs"
ha apps logs "$SCRYPTED_SLUG" 2>/dev/null \
  | grep -Ei 'rebroadcast|rtsp|Bad Request|Unsupported Transport|EADDRINUSE|ECONN|Unable to|error' \
  | tail -n "$LINES" \
  | redact || true

section "Add-on State"
for slug in "$FRIGATE_SLUG" "$SCRYPTED_SLUG"; do
  curl -fsS -H "Authorization: Bearer $SUPERVISOR_TOKEN" "http://supervisor/addons/$slug/info" 2>/dev/null \
    | jq '{slug:.data.slug,state:.data.state,version:.data.version,repository:.data.repository}' \
    | redact || true
done
REMOTE

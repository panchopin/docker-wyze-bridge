#!/bin/sh
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)

STREAMS="${HA_WHEP_SOAK_STREAMS:-}"
DURATION="${HA_WHEP_SOAK_SECONDS:-3600}"
INTERVAL="${HA_WHEP_SOAK_INTERVAL_SECONDS:-30}"
LOG_LINES="${HA_WHEP_SOAK_LOG_LINES:-160}"
PROD_SLUG="${HA_PROD_ADDON_SLUG:-local_docker_wyze_bridge_v4}"

usage() {
  cat <<EOF
Usage: HA_WHEP_SOAK_STREAMS="deck-sub garage-sub south-yard" scripts/ha_phase4_whep_soak.sh

Runs the read-only Phase 4 live WHEP soak from the Home Assistant host. The
default duration is one hour. The script fails if production health is not
ready, if any named stream is not video-ready through the WHEP proxy, if an
audio-ready stream has not forwarded audio packets, if Frigate FPS is unhealthy,
or if recent logs show obvious WHEP/audio-only wedge symptoms.

Environment:
  HA_WHEP_SOAK_STREAMS            required, space/comma-separated stream names
  HA_WHEP_SOAK_SECONDS            default: $DURATION
  HA_WHEP_SOAK_INTERVAL_SECONDS   default: $INTERVAL
  HA_WHEP_SOAK_LOG_LINES          default: $LOG_LINES
  HA_PROD_ADDON_SLUG              default: $PROD_SLUG
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

STREAM_LIST=$(printf '%s' "$STREAMS" | tr ',' ' ' | xargs)
if [ -z "$STREAM_LIST" ]; then
  echo "Missing HA_WHEP_SOAK_STREAMS. Name the WHEP streams to prove." >&2
  exit 1
fi

for stream in $STREAM_LIST; do
  case "$stream" in
    ""|*[!A-Za-z0-9_.-]*)
      echo "Invalid stream name '$stream': only letters, numbers, '.', '_' and '-' are allowed." >&2
      exit 1
      ;;
  esac
done

validate_number "HA_WHEP_SOAK_SECONDS" "$DURATION"
validate_number "HA_WHEP_SOAK_INTERVAL_SECONDS" "$INTERVAL"
validate_number "HA_WHEP_SOAK_LOG_LINES" "$LOG_LINES"
validate_slug "HA_PROD_ADDON_SLUG" "$PROD_SLUG"

"$SCRIPT_DIR/ha_ssh.sh" "HA_WHEP_STREAMS='$STREAM_LIST' HA_WHEP_DURATION=$DURATION HA_WHEP_INTERVAL=$INTERVAL HA_WHEP_LOG_LINES=$LOG_LINES HA_WHEP_PROD_SLUG=$PROD_SLUG sh -s" <<'REMOTE'
set -eu

STREAMS="$HA_WHEP_STREAMS"
DURATION="$HA_WHEP_DURATION"
INTERVAL="$HA_WHEP_INTERVAL"
LOG_LINES="$HA_WHEP_LOG_LINES"
PROD_SLUG="$HA_WHEP_PROD_SLUG"
FAIL=0

section() {
  printf '\n## %s\n' "$1"
}

mark_fail() {
  echo "FAIL: $1"
  FAIL=1
}

redact() {
  sed -E 's/api=[^" ]+/api=<redacted>/g'
}

check_health_ready() {
  health=$(curl -fsS --max-time 8 http://172.30.32.1:5000/health 2>/dev/null || true)
  printf 'health=%s\n' "${health:-<empty>}" | redact
  if [ -z "$health" ]; then
    mark_fail "production /health did not respond"
    return
  fi
  if ! printf '%s\n' "$health" | jq -e '.mtx_alive == true and .wyze_authed == true' >/dev/null 2>&1; then
    mark_fail "production health must report mtx_alive=true and wyze_authed=true before/during WHEP soak"
  fi
}

check_stream() {
  stream="$1"
  details=$(curl -fsS --max-time 8 "http://172.30.32.1:5000/health/details?stream=$stream" 2>/dev/null || true)
  if [ -z "$details" ]; then
    mark_fail "$stream health/details did not respond"
    return
  fi
  summary=$(printf '%s\n' "$details" | jq -c '{stream:.stream,whep_reachable:.whep_proxy.reachable,whep_status:.whep_proxy.status_code,upstream_state:.whep_proxy.data.upstream_state,video_ready:.whep_proxy.data.video_ready,audio_ready:.whep_proxy.data.audio_ready,audio_packets_seen:(.whep_proxy.data.audio_packets_seen // 0),has_ever_had_media:.whep_proxy.data.has_ever_had_media,mediamtx_reachable:.mediamtx.reachable,mediamtx_status:.mediamtx.status_code}' 2>/dev/null || true)
  printf '%s\n' "${summary:-$stream: invalid health/details JSON}" | redact
  if [ -z "$summary" ]; then
    mark_fail "$stream health/details returned invalid JSON"
    return
  fi
  if ! printf '%s\n' "$details" | jq -e '.whep_proxy.reachable == true and .whep_proxy.data.video_ready == true and .whep_proxy.data.has_ever_had_media == true' >/dev/null 2>&1; then
    mark_fail "$stream WHEP proxy must be reachable with video_ready=true and has_ever_had_media=true"
  fi
  if printf '%s\n' "$details" | jq -e '.whep_proxy.data.upstream_state == "new"' >/dev/null 2>&1; then
    mark_fail "$stream WHEP upstream_state must not stay new"
  fi
  if printf '%s\n' "$details" | jq -e '(.whep_proxy.data.audio_ready == true) and (((.whep_proxy.data.audio_packets_seen // 0) | tonumber) <= 0)' >/dev/null 2>&1; then
    mark_fail "$stream reports audio_ready=true without audio packets"
  fi
}

check_frigate() {
  stats=$(curl -fsS --max-time 8 http://ccab4aaf-frigate:5000/api/stats 2>/dev/null || true)
  if [ -z "$stats" ]; then
    mark_fail "Frigate stats did not respond"
    return
  fi
  printf '%s\n' "$stats" \
    | jq -r '.cameras | to_entries[] | [.key, .value.camera_fps, .value.process_fps, .value.skipped_fps] | @tsv' \
    | redact
  bad=$(printf '%s\n' "$stats" | jq -r '.cameras | to_entries[] | select((((.value.camera_fps // 0) | tonumber) <= 0) or (((.value.process_fps // 0) | tonumber) <= 0) or (((.value.skipped_fps // 0) | tonumber) != 0)) | .key' 2>/dev/null || true)
  if [ -n "$bad" ]; then
    printf 'Unhealthy Frigate cameras:\n%s\n' "$bad"
    mark_fail "Frigate cameras must have positive camera/process FPS and skipped_fps=0"
  fi
}

section "Phase 4 WHEP Soak"
echo "streams=$STREAMS"
echo "duration_seconds=$DURATION"
echo "interval_seconds=$INTERVAL"

start=$(date +%s)
sample=0

while :; do
  now=$(date +%s)
  elapsed=$((now - start))
  sample=$((sample + 1))
  section "Sample $sample elapsed=${elapsed}s"
  check_health_ready
  for stream in $STREAMS; do
    check_stream "$stream"
  done
  check_frigate
  if [ "$elapsed" -ge "$DURATION" ]; then
    break
  fi
  sleep "$INTERVAL"
done

section "Recent WHEP / Bridge Logs"
logs=$(ha apps logs "$PROD_SLUG" 2>/dev/null \
  | sed -E 's/api=[^" ]+/api=<redacted>/g' \
  | grep -E 'WHEP|1 track \(G711\)|audio-only|video_ready=false|upstream_state="new"|listen tcp|empty catalog|alias refresh failed' \
  | tail -n "$LOG_LINES" || true)
printf '%s\n' "${logs:-<no matching log lines>}" | redact

if printf '%s\n' "$logs" | grep -q 'listen tcp :58888: bind: address already in use'; then
  mark_fail "recent bridge logs still show the :58888 bind conflict"
fi
if printf '%s\n' "$logs" | grep -Eiq '1 track \(G711\)|audio-only|video_ready=false|upstream_state="new"'; then
  mark_fail "recent bridge logs show possible WHEP/audio-only wedge symptoms"
fi
if printf '%s\n' "$logs" | grep -Eiq 'empty catalog|alias refresh failed'; then
  mark_fail "recent bridge logs show catalog/alias startup errors"
fi

section "Result"
if [ "$FAIL" -eq 0 ]; then
  echo "PASS: Phase 4 WHEP soak passed for all named streams."
else
  echo "FAIL: Phase 4 WHEP soak failed."
fi

exit "$FAIL"
REMOTE

#!/bin/sh
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)

PROD_SLUG="${HA_PROD_ADDON_SLUG:-local_docker_wyze_bridge_v4}"
LINES="${HA_PROD_RECOVERY_LOG_LINES:-120}"

usage() {
  cat <<EOF
Usage: scripts/ha_prod_recovery_verify.sh

Runs a read-only pass/fail production recovery gate after an approved Home
Assistant host recovery action. It verifies the production bridge health,
sanitized Supervisor metadata, recent bridge logs, and Frigate FPS. It does
not stop, start, rebuild, reboot, or edit anything.

Environment:
  HA_PROD_ADDON_SLUG            default: $PROD_SLUG
  HA_PROD_RECOVERY_LOG_LINES    default: $LINES
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

validate_lines() {
  case "$LINES" in
    ""|*[!0-9]*)
      echo "Invalid HA_PROD_RECOVERY_LOG_LINES: use a positive integer." >&2
      exit 1
      ;;
    0)
      echo "Invalid HA_PROD_RECOVERY_LOG_LINES: use a positive integer." >&2
      exit 1
      ;;
  esac
}

validate_slug "HA_PROD_ADDON_SLUG" "$PROD_SLUG"
validate_lines

"$SCRIPT_DIR/ha_ssh.sh" "HA_VERIFY_PROD_SLUG=$PROD_SLUG HA_VERIFY_LINES=$LINES sh -s" <<'REMOTE'
set -eu

PROD_SLUG="$HA_VERIFY_PROD_SLUG"
LINES="$HA_VERIFY_LINES"
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

section "Production Health Gate"
HEALTH=$(curl -fsS --max-time 8 http://172.30.32.1:5000/health 2>/dev/null || true)
printf '%s\n' "${HEALTH:-<empty>}" | redact

if [ -z "$HEALTH" ]; then
  mark_fail "production /health did not respond"
elif ! printf '%s\n' "$HEALTH" | jq -e '.mtx_alive == true and .wyze_authed == true' >/dev/null 2>&1; then
  mark_fail "production /health must report mtx_alive=true and wyze_authed=true"
fi

section "Production Supervisor Metadata Gate"
INFO=$(curl -fsS -H "Authorization: Bearer $SUPERVISOR_TOKEN" "http://supervisor/addons/$PROD_SLUG/info" 2>/dev/null || true)
if [ -z "$INFO" ]; then
  echo "<empty>"
  mark_fail "Supervisor add-on metadata did not respond"
else
  printf '%s\n' "$INFO" \
    | jq '{slug:.data.slug,state:.data.state,version:.data.version,repository:.data.repository,host_network:.data.host_network,network:.data.network,option_keys:(.data.options|keys? // [])}' \
    | redact
  STATE=$(printf '%s\n' "$INFO" | jq -r '.data.state // ""')
  if [ "$STATE" != "started" ]; then
    mark_fail "production add-on state must be started"
  fi
fi

section "Bridge Log Gate"
LOGS=$(ha apps logs "$PROD_SLUG" 2>/dev/null \
  | sed -E 's/api=[^" ]+/api=<redacted>/g' \
  | grep -E 'MediaMTX|listen tcp|listener opened|empty catalog|alias refresh failed|ready|FILTER ALLOWING|1 track \(G711\)|audio-only|video_ready=false|upstream_state="new"' \
  | tail -n "$LINES" || true)
printf '%s\n' "${LOGS:-<no matching log lines>}" | redact

if printf '%s\n' "$LOGS" | grep -q 'listen tcp :58888: bind: address already in use'; then
  mark_fail "recent bridge logs still show the :58888 bind conflict"
fi
if printf '%s\n' "$LOGS" | grep -Eiq 'empty catalog|alias refresh failed'; then
  mark_fail "recent bridge logs still show catalog/alias startup errors"
fi
if printf '%s\n' "$LOGS" | grep -Eiq '1 track \(G711\)|audio-only|video_ready=false|upstream_state="new"'; then
  mark_fail "recent bridge logs show possible WHEP/audio-only wedge symptoms"
fi

section "Frigate FPS Gate"
STATS=$(curl -fsS --max-time 8 http://ccab4aaf-frigate:5000/api/stats 2>/dev/null || true)
if [ -z "$STATS" ]; then
  echo "<empty>"
  mark_fail "Frigate stats did not respond"
else
  printf '%s\n' "$STATS" \
    | jq -r '.cameras | to_entries[] | [.key, .value.camera_fps, .value.process_fps, .value.skipped_fps] | @tsv' \
    | redact
  BAD=$(printf '%s\n' "$STATS" | jq -r '.cameras | to_entries[] | select((((.value.camera_fps // 0) | tonumber) <= 0) or (((.value.process_fps // 0) | tonumber) <= 0) or (((.value.skipped_fps // 0) | tonumber) != 0)) | .key' 2>/dev/null || true)
  if [ -n "$BAD" ]; then
    printf 'Unhealthy Frigate cameras:\n%s\n' "$BAD"
    mark_fail "Frigate cameras must have positive camera/process FPS and skipped_fps=0"
  fi
fi

section "Result"
if [ "$FAIL" -eq 0 ]; then
  echo "PASS: production bridge is recovered enough to resume the remaining live Phase 4/5 gates."
else
  echo "FAIL: production bridge is not ready for the remaining live Phase 4/5 gates."
fi

exit "$FAIL"
REMOTE

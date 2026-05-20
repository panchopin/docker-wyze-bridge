#!/bin/sh
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)

PROD_SLUG="${HA_PROD_ADDON_SLUG:-local_docker_wyze_bridge_v4}"
DEV_SLUG="${HA_DEV_ADDON_SLUG:-local_docker_wyze_bridge_local}"
LINES="${HA_BRIDGE_DOCTOR_LOG_LINES:-80}"

usage() {
  cat <<EOF
Usage: scripts/ha_bridge_doctor.sh

Runs read-only Home Assistant checks for Wyze Bridge production/dev handoff
state, MediaMTX health, duplicate bridge add-ons, host port visibility, and
Frigate FPS. It does not stop, start, rebuild, reboot, or edit anything.

Environment:
  HA_PROD_ADDON_SLUG          default: $PROD_SLUG
  HA_DEV_ADDON_SLUG           default: $DEV_SLUG
  HA_BRIDGE_DOCTOR_LOG_LINES  default: $LINES
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
      echo "Invalid HA_BRIDGE_DOCTOR_LOG_LINES: use a positive integer." >&2
      exit 1
      ;;
    0)
      echo "Invalid HA_BRIDGE_DOCTOR_LOG_LINES: use a positive integer." >&2
      exit 1
      ;;
  esac
}

validate_slug "HA_PROD_ADDON_SLUG" "$PROD_SLUG"
validate_slug "HA_DEV_ADDON_SLUG" "$DEV_SLUG"
validate_lines

redact() {
  sed -E 's/api=[^" ]+/api=<redacted>/g'
}

section() {
  printf '\n## %s\n' "$1"
}

remote() {
  "$SCRIPT_DIR/ha_ssh.sh" "$@"
}

section "Bridge Add-ons"
remote 'ha apps --raw-json 2>/dev/null | jq -r ".data.addons[]? | select((.slug|test(\"wyze|bridge\";\"i\")) or (.name|test(\"wyze|bridge\";\"i\"))) | [.slug,.name,.state,.repository,.version] | @tsv"' \
  | redact || true

section "Production Health"
remote 'curl -fsS --max-time 8 http://172.30.32.1:5000/health || true' | redact || true

section "Production Supervisor Metadata"
remote "curl -fsS -H \"Authorization: Bearer \$SUPERVISOR_TOKEN\" http://supervisor/addons/$PROD_SLUG/info | jq '{slug:.data.slug,state:.data.state,version:.data.version,repository:.data.repository,host_network:.data.host_network,network:.data.network,option_keys:(.data.options|keys? // [])}'" \
  | redact || true

section "MediaMTX / Bridge Log Tail"
remote "ha apps logs $PROD_SLUG | sed -E 's/api=[^\" ]+/api=<redacted>/g' | grep -E 'MediaMTX|listen tcp|listener opened|empty catalog|alias refresh failed|ready|FILTER ALLOWING' | tail -n $LINES" \
  | redact || true

section "Host Port Visibility"
remote 'for cmd in "ss -ltnp" "netstat -ltnp" "lsof -nP -iTCP:58888 -sTCP:LISTEN" "fuser -n tcp 58888" "docker ps --format {{.ID}}\\t{{.Names}}\\t{{.Status}}\\t{{.Ports}}"; do printf "CMD %s\n" "$cmd"; sh -c "$cmd" 2>&1 | sed -E "s/api=[^\" ]+/api=<redacted>/g" | grep -E "58888|wyze|bridge|mediamtx|not found|Permission|Operation|COMMAND|LISTEN|tcp|docker" | head -n 30 || true; done' \
  | redact || true

section "Host Log Clues"
remote 'ha host logs -n 500 2>/dev/null | sed -E "s/api=[^\" ]+/api=<redacted>/g" | grep -Ei "58888|wyze|mediamtx|docker_wyze|bind|address already|net=host" | tail -n 80 || true' \
  | redact || true

section "Frigate FPS"
remote 'curl -fsS --max-time 8 http://ccab4aaf-frigate:5000/api/stats | jq -r ".cameras | to_entries[] | [.key, .value.camera_fps, .value.process_fps, .value.skipped_fps] | @tsv" || true' \
  | redact || true

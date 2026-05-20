#!/bin/sh
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
ROOT_DIR=$(CDPATH= cd -- "$SCRIPT_DIR/.." && pwd)

PROD_SLUG="${HA_PROD_ADDON_SLUG:-local_docker_wyze_bridge_v4}"
BRIDGE_BASE="${HA_PHASE5_BRIDGE_BASE:-http://172.30.32.1:5000}"
LOG_LINES="${HA_PHASE5_LOG_LINES:-160}"
MIN_CAMERAS="${HA_PHASE5_MIN_CAMERAS:-1}"
EXPECTED_REPOSITORY="${HA_PHASE5_EXPECTED_REPOSITORY:-}"
EXPECTED_VERSION="${HA_PHASE5_EXPECTED_VERSION:-}"

usage() {
  cat <<EOF
Usage: scripts/ha_phase5_prod_overlay_api_verify.sh

Runs the read-only Phase 5 production overlay/API proof after an approved
production overlay-built rebuild. It first verifies the local overlay build,
then checks production Supervisor metadata, /health, /api, /api/ready, and
recent logs. It does not stop, start, rebuild, reboot, or edit anything.

Environment:
  HA_PROD_ADDON_SLUG               default: $PROD_SLUG
  HA_PHASE5_BRIDGE_BASE            default: $BRIDGE_BASE
  HA_PHASE5_LOG_LINES              default: $LOG_LINES
  HA_PHASE5_MIN_CAMERAS            default: $MIN_CAMERAS
  HA_PHASE5_EXPECTED_REPOSITORY    optional; fail unless Supervisor repository matches
  HA_PHASE5_EXPECTED_VERSION       optional; fail unless Supervisor version matches
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

validate_base_url() {
  name="$1"
  value="$2"
  case "$value" in
    http://*) host="${value#http://}" ;;
    https://*) host="${value#https://}" ;;
    *)
      echo "Invalid $name: use a simple http(s) URL without a path." >&2
      exit 1
      ;;
  esac
  case "$host" in
    ""|*/*|*\?*|*\&*|*\=*|*[!A-Za-z0-9_.:-]*)
      echo "Invalid $name: use a simple http(s) URL without a path." >&2
      exit 1
      ;;
  esac
}

validate_optional_metadata() {
  name="$1"
  value="$2"
  case "$value" in
    ""|*[!A-Za-z0-9_.:+/-]*)
      if [ -n "$value" ]; then
        echo "Invalid $name: use only URL/version-safe characters, no spaces." >&2
        exit 1
      fi
      ;;
  esac
}

validate_number "HA_PHASE5_LOG_LINES" "$LOG_LINES"
validate_number "HA_PHASE5_MIN_CAMERAS" "$MIN_CAMERAS"
validate_slug "HA_PROD_ADDON_SLUG" "$PROD_SLUG"
validate_base_url "HA_PHASE5_BRIDGE_BASE" "$BRIDGE_BASE"
validate_optional_metadata "HA_PHASE5_EXPECTED_REPOSITORY" "$EXPECTED_REPOSITORY"
validate_optional_metadata "HA_PHASE5_EXPECTED_VERSION" "$EXPECTED_VERSION"

printf '\n## Local Overlay Build Check\n'
"$ROOT_DIR/scripts/build.sh" --check

"$SCRIPT_DIR/ha_ssh.sh" "HA_PHASE5_PROD_SLUG=$PROD_SLUG HA_PHASE5_BRIDGE_BASE=$BRIDGE_BASE HA_PHASE5_LOG_LINES=$LOG_LINES HA_PHASE5_MIN_CAMERAS=$MIN_CAMERAS HA_PHASE5_EXPECTED_REPOSITORY=$EXPECTED_REPOSITORY HA_PHASE5_EXPECTED_VERSION=$EXPECTED_VERSION sh -s" <<'REMOTE'
set -eu

PROD_SLUG="$HA_PHASE5_PROD_SLUG"
BRIDGE_BASE="$HA_PHASE5_BRIDGE_BASE"
LOG_LINES="$HA_PHASE5_LOG_LINES"
MIN_CAMERAS="$HA_PHASE5_MIN_CAMERAS"
EXPECTED_REPOSITORY="$HA_PHASE5_EXPECTED_REPOSITORY"
EXPECTED_VERSION="$HA_PHASE5_EXPECTED_VERSION"
FAIL=0
API_TOKEN=""

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

curl_bridge() {
  path="$1"
  if [ -n "$API_TOKEN" ]; then
    curl -sS --max-time 8 -H "api: $API_TOKEN" -w '\n%{http_code}' "$BRIDGE_BASE$path" 2>/dev/null || printf '\n000'
  else
    curl -sS --max-time 8 -w '\n%{http_code}' "$BRIDGE_BASE$path" 2>/dev/null || printf '\n000'
  fi
}

json_field() {
  body="$1"
  filter="$2"
  printf '%s\n' "$body" | jq -r "$filter" 2>/dev/null || printf '0\n'
}

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
  REPOSITORY=$(printf '%s\n' "$INFO" | jq -r '.data.repository // ""')
  VERSION=$(printf '%s\n' "$INFO" | jq -r '.data.version // ""')
  STORED_API=$(printf '%s\n' "$INFO" | jq -r '.data.options.WB_API // .data.options.wb_api // ""' 2>/dev/null || true)
  WYZE_EMAIL=$(printf '%s\n' "$INFO" | jq -r '.data.options.WYZE_EMAIL // ""' 2>/dev/null || true)

  if [ "$STATE" != "started" ]; then
    mark_fail "production add-on state must be started"
  fi
  if [ -n "$EXPECTED_REPOSITORY" ] && [ "$REPOSITORY" != "$EXPECTED_REPOSITORY" ]; then
    mark_fail "production add-on repository must match HA_PHASE5_EXPECTED_REPOSITORY"
  fi
  if [ -n "$EXPECTED_VERSION" ] && [ "$VERSION" != "$EXPECTED_VERSION" ]; then
    mark_fail "production add-on version must match HA_PHASE5_EXPECTED_VERSION"
  fi

  if [ -n "$STORED_API" ] && [ "$STORED_API" != "null" ]; then
    API_TOKEN="$STORED_API"
  elif [ -n "$WYZE_EMAIL" ] && [ "$WYZE_EMAIL" != "null" ]; then
    API_TOKEN=$(printf '%s' "$WYZE_EMAIL" \
      | sha256sum \
      | awk '{print $1}' \
      | xxd -r -p \
      | base64 \
      | tr '+/' '-_' \
      | tr -d '=\n' \
      | cut -c1-40)
  fi
fi

if [ -n "$API_TOKEN" ]; then
  echo "auth=api-header"
else
  echo "auth=none"
fi

section "Production Health Gate"
HEALTH=$(curl -fsS --max-time 8 "$BRIDGE_BASE/health" 2>/dev/null || true)
printf '%s\n' "${HEALTH:-<empty>}" | redact
if [ -z "$HEALTH" ]; then
  mark_fail "production /health did not respond"
elif ! printf '%s\n' "$HEALTH" | jq -e '.mtx_alive == true and .wyze_authed == true' >/dev/null 2>&1; then
  mark_fail "production /health must report mtx_alive=true and wyze_authed=true"
fi

section "Production API Catalog Gate"
api_result=$(curl_bridge "/api")
api_code=$(printf '%s\n' "$api_result" | tail -n 1)
api_body=$(printf '%s\n' "$api_result" | sed '$d')
ready_result=$(curl_bridge "/api/ready")
ready_code=$(printf '%s\n' "$ready_result" | tail -n 1)
ready_body=$(printf '%s\n' "$ready_result" | sed '$d')

camera_count=$(json_field "$api_body" '(.cameras // {}) | length')
enabled_count=$(json_field "$api_body" '(.cameras // {}) | to_entries | map(select((.value.enabled // true) != false)) | length')
native_url_count=$(json_field "$api_body" '(.cameras // {}) | to_entries | map(select((.value.enabled // true) != false and ((.value.native_rtsp_url // "") != ""))) | length')
ready_status=$(json_field "$ready_body" '.status // ""')
ready_body_keys=$(json_field "$ready_body" 'if type == "object" then (keys | sort | join(",")) else type end')
ready_marker="$ready_status"
if printf '%s\n' "$ready_body" | grep -Fq 'Could not find camera [ready]'; then
  ready_marker="camera_lookup_fallback"
fi

printf 'api_status=%s ready_status_code=%s ready_state=%s ready_marker=%s ready_body_keys=%s cameras=%s enabled_cameras=%s native_rtsp_urls=%s min_expected_cameras=%s\n' \
  "$api_code" "$ready_code" "$ready_status" "$ready_marker" "$ready_body_keys" "$camera_count" "$enabled_count" "$native_url_count" "$MIN_CAMERAS" | redact

if [ "$api_code" != "200" ]; then
  mark_fail "/api must return 200"
fi
if [ "$ready_code" != "200" ]; then
  mark_fail "/api/ready must return 200"
fi
if [ "$camera_count" -lt "$MIN_CAMERAS" ]; then
  mark_fail "/api camera catalog must meet HA_PHASE5_MIN_CAMERAS"
fi
if [ "$enabled_count" -gt 0 ] && [ "$native_url_count" -lt "$enabled_count" ]; then
  mark_fail "every enabled camera must expose native_rtsp_url after overlay-built rebuild"
fi
if [ "$ready_status" != "ready" ]; then
  mark_fail "/api/ready must report status=ready"
fi
if [ "$ready_marker" = "camera_lookup_fallback" ]; then
  mark_fail "production /api/ready is falling through to camera lookup; overlay-built readiness route is not live"
fi

section "Recent Production Logs"
logs=$(ha apps logs "$PROD_SLUG" 2>/dev/null \
  | sed -E 's/api=[^" ]+/api=<redacted>/g' \
  | grep -E 'MediaMTX|listen tcp|listener opened|empty catalog|alias refresh failed|ready|whep|1 track \(G711\)|audio-only|video_ready=false|upstream_state="new"' \
  | tail -n "$LOG_LINES" || true)
printf '%s\n' "${logs:-<no matching log lines>}" | redact

if printf '%s\n' "$logs" | grep -q 'listen tcp :58888: bind: address already in use'; then
  mark_fail "recent bridge logs still show the :58888 bind conflict"
fi
if printf '%s\n' "$logs" | grep -Eiq 'empty catalog|alias refresh failed'; then
  mark_fail "recent bridge logs still show catalog/alias startup errors"
fi
if printf '%s\n' "$logs" | grep -Eiq '1 track \(G711\)|audio-only|video_ready=false|upstream_state="new"'; then
  mark_fail "recent bridge logs show possible WHEP/audio-only wedge symptoms"
fi

section "Result"
if [ "$FAIL" -eq 0 ]; then
  echo "PASS: production Phase 5 overlay/API proof passed."
else
  echo "FAIL: production Phase 5 overlay/API proof failed."
fi

exit "$FAIL"
REMOTE

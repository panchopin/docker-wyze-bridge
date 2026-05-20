#!/bin/sh
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)

DURATION="${HA_PHASE2_STARTUP_SECONDS:-60}"
INTERVAL="${HA_PHASE2_STARTUP_INTERVAL_SECONDS:-2}"
LOG_LINES="${HA_PHASE2_STARTUP_LOG_LINES:-160}"
PROD_SLUG="${HA_PROD_ADDON_SLUG:-local_docker_wyze_bridge_v4}"
BRIDGE_BASE="${HA_PHASE2_BRIDGE_BASE:-http://172.30.32.1:5000}"

usage() {
  cat <<EOF
Usage: scripts/ha_phase2_prod_startup_soak.sh

Runs the read-only production Phase 2 API/startup soak from the Home Assistant
host after an approved recovery or restart. It polls /api and /api/ready,
verifies that the catalog never becomes empty, verifies native RTSP URLs stay
present for every enabled camera, and checks recent logs for catalog/alias
startup errors.

Environment:
  HA_PHASE2_STARTUP_SECONDS            default: $DURATION
  HA_PHASE2_STARTUP_INTERVAL_SECONDS   default: $INTERVAL
  HA_PHASE2_STARTUP_LOG_LINES          default: $LOG_LINES
  HA_PROD_ADDON_SLUG                   default: $PROD_SLUG
  HA_PHASE2_BRIDGE_BASE                default: $BRIDGE_BASE
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

validate_number "HA_PHASE2_STARTUP_SECONDS" "$DURATION"
validate_number "HA_PHASE2_STARTUP_INTERVAL_SECONDS" "$INTERVAL"
validate_number "HA_PHASE2_STARTUP_LOG_LINES" "$LOG_LINES"
validate_slug "HA_PROD_ADDON_SLUG" "$PROD_SLUG"
validate_base_url "HA_PHASE2_BRIDGE_BASE" "$BRIDGE_BASE"

"$SCRIPT_DIR/ha_ssh.sh" "HA_PHASE2_DURATION=$DURATION HA_PHASE2_INTERVAL=$INTERVAL HA_PHASE2_LOG_LINES=$LOG_LINES HA_PHASE2_PROD_SLUG=$PROD_SLUG HA_PHASE2_BRIDGE_BASE=$BRIDGE_BASE sh -s" <<'REMOTE'
set -eu

DURATION="$HA_PHASE2_DURATION"
INTERVAL="$HA_PHASE2_INTERVAL"
LOG_LINES="$HA_PHASE2_LOG_LINES"
PROD_SLUG="$HA_PHASE2_PROD_SLUG"
BRIDGE_BASE="$HA_PHASE2_BRIDGE_BASE"
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

section "Production Phase 2 Startup/API Soak"
echo "duration_seconds=$DURATION"
echo "interval_seconds=$INTERVAL"
echo "bridge_base=$BRIDGE_BASE"

INFO=$(curl -fsS -H "Authorization: Bearer $SUPERVISOR_TOKEN" "http://supervisor/addons/$PROD_SLUG/info" 2>/dev/null || true)
if [ -n "$INFO" ]; then
  STORED_API=$(printf '%s\n' "$INFO" | jq -r '.data.options.WB_API // .data.options.wb_api // ""' 2>/dev/null || true)
  WYZE_EMAIL=$(printf '%s\n' "$INFO" | jq -r '.data.options.WYZE_EMAIL // ""' 2>/dev/null || true)
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

samples=0
api_non_200=0
ready_non_200=0
ready_not_ready=0
ready_camera_lookup_error=0
empty_catalog=0
loading_samples=0
native_url_miss=0
min_camera_count=
max_camera_count=0
min_native_url_count=
max_native_url_count=0

start=$(date +%s)
while :; do
  now=$(date +%s)
  elapsed=$((now - start))
  samples=$((samples + 1))

  api_result=$(curl_bridge "/api")
  api_code=$(printf '%s\n' "$api_result" | tail -n 1)
  api_body=$(printf '%s\n' "$api_result" | sed '$d')

  ready_result=$(curl_bridge "/api/ready")
  ready_code=$(printf '%s\n' "$ready_result" | tail -n 1)
  ready_body=$(printf '%s\n' "$ready_result" | sed '$d')

  if [ "$api_code" != "200" ]; then
    api_non_200=$((api_non_200 + 1))
  fi
  if [ "$ready_code" != "200" ]; then
    ready_non_200=$((ready_non_200 + 1))
  fi

  ready_status=$(json_field "$ready_body" '.status // ""')
  if [ "$ready_status" != "ready" ]; then
    ready_not_ready=$((ready_not_ready + 1))
  fi
  if printf '%s\n' "$ready_body" | grep -Fq 'Could not find camera [ready]'; then
    ready_camera_lookup_error=$((ready_camera_lookup_error + 1))
    ready_marker="camera_lookup_fallback"
  else
    ready_marker="$ready_status"
  fi

  status=$(json_field "$api_body" '.status // ""')
  if [ "$status" = "loading" ]; then
    loading_samples=$((loading_samples + 1))
  fi

  camera_count=$(json_field "$api_body" '(.cameras // {}) | length')
  native_url_count=$(json_field "$api_body" '(.cameras // {}) | to_entries | map(select((.value.enabled // true) != false and ((.value.native_rtsp_url // "") != ""))) | length')

  if [ "$camera_count" -eq 0 ]; then
    empty_catalog=$((empty_catalog + 1))
  fi
  if [ "$native_url_count" -lt "$camera_count" ]; then
    native_url_miss=$((native_url_miss + 1))
  fi

  if [ -z "$min_camera_count" ] || [ "$camera_count" -lt "$min_camera_count" ]; then
    min_camera_count="$camera_count"
  fi
  if [ "$camera_count" -gt "$max_camera_count" ]; then
    max_camera_count="$camera_count"
  fi
  if [ -z "$min_native_url_count" ] || [ "$native_url_count" -lt "$min_native_url_count" ]; then
    min_native_url_count="$native_url_count"
  fi
  if [ "$native_url_count" -gt "$max_native_url_count" ]; then
    max_native_url_count="$native_url_count"
  fi

  printf 'sample=%s elapsed=%ss api_status=%s ready_status_code=%s ready_state=%s ready_marker=%s cameras=%s native_rtsp_urls=%s\n' \
    "$samples" "$elapsed" "$api_code" "$ready_code" "$ready_status" "$ready_marker" "$camera_count" "$native_url_count" | redact

  if [ "$elapsed" -ge "$DURATION" ]; then
    break
  fi
  sleep "$INTERVAL"
done

section "Summary"
echo "samples=$samples"
echo "api_non_200=$api_non_200"
echo "ready_non_200=$ready_non_200"
echo "ready_not_ready_samples=$ready_not_ready"
echo "ready_camera_lookup_error_samples=$ready_camera_lookup_error"
echo "loading_samples=$loading_samples"
echo "empty_catalog_samples=$empty_catalog"
echo "native_rtsp_url_miss_samples=$native_url_miss"
echo "min_camera_count=$min_camera_count"
echo "max_camera_count=$max_camera_count"
echo "min_native_rtsp_url_present_count=$min_native_url_count"
echo "max_native_rtsp_url_present_count=$max_native_url_count"

if [ "$api_non_200" -ne 0 ]; then
  mark_fail "/api must return 200 for every sample"
fi
if [ "$ready_non_200" -ne 0 ]; then
  mark_fail "/api/ready must return 200 for every sample"
fi
if [ "$ready_not_ready" -ne 0 ]; then
  mark_fail "/api/ready must report status=ready for every sample"
fi
if [ "$ready_camera_lookup_error" -ne 0 ]; then
  mark_fail "/api/ready is falling through to camera lookup instead of the readiness route"
fi
if [ "$loading_samples" -ne 0 ]; then
  mark_fail "/api must not still report loading during this proof window"
fi
if [ "$empty_catalog" -ne 0 ]; then
  mark_fail "/api camera catalog must never be empty"
fi
if [ "$native_url_miss" -ne 0 ]; then
  mark_fail "every enabled camera must keep a native_rtsp_url across the soak"
fi

section "Recent Startup Logs"
logs=$(ha apps logs "$PROD_SLUG" 2>/dev/null \
  | sed -E 's/api=[^" ]+/api=<redacted>/g' \
  | grep -E 'sidecar|alias|catalog|ready|empty catalog|alias refresh failed|authenticated bridge catalog did not populate|authenticated bridge API did not report ready|listen tcp :58888' \
  | tail -n "$LOG_LINES" || true)
printf '%s\n' "${logs:-<no matching log lines>}" | redact

if printf '%s\n' "$logs" | grep -Eiq 'empty catalog|alias refresh failed|authenticated bridge catalog did not populate|authenticated bridge API did not report ready'; then
  mark_fail "recent bridge logs still show catalog/alias startup errors"
fi
if printf '%s\n' "$logs" | grep -q 'listen tcp :58888: bind: address already in use'; then
  mark_fail "recent bridge logs still show the :58888 bind conflict"
fi

section "Result"
if [ "$FAIL" -eq 0 ]; then
  echo "PASS: production Phase 2 startup/API soak passed."
else
  echo "FAIL: production Phase 2 startup/API soak failed."
fi

exit "$FAIL"
REMOTE

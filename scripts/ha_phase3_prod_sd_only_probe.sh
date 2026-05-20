#!/bin/sh
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
ROOT_DIR=$(CDPATH= cd -- "$SCRIPT_DIR/.." && pwd)
TMP_DIR="$ROOT_DIR/tmp"
STAMP=$(date +%Y%m%d_%H%M%S)
OUT="$TMP_DIR/phase3_prod_sd_only_${STAMP}.txt"

PROD_SLUG="${HA_PROD_ADDON_SLUG:-local_docker_wyze_bridge_v4}"
BRIDGE_BASE="${HA_PHASE3_BRIDGE_BASE:-http://172.30.32.1:5000}"

usage() {
  cat <<EOF
Usage: scripts/ha_phase3_prod_sd_only_probe.sh

Runs a read-only production Phase 3 SD_ONLY proof probe from the Home Assistant
host. It inspects Supervisor options, authenticated bridge catalog,
/api/<camera>/stream-config, and go2rtc aliases. It does not stop, start,
restart, rebuild, update, POST, or edit anything.

Environment:
  HA_PROD_ADDON_SLUG      default: $PROD_SLUG
  HA_PHASE3_BRIDGE_BASE   default: $BRIDGE_BASE
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

validate_slug "HA_PROD_ADDON_SLUG" "$PROD_SLUG"
validate_base_url "HA_PHASE3_BRIDGE_BASE" "$BRIDGE_BASE"

mkdir -p "$TMP_DIR"

set +e
"$SCRIPT_DIR/ha_ssh.sh" "HA_PHASE3_PROD_SLUG=$PROD_SLUG HA_PHASE3_BRIDGE_BASE=$BRIDGE_BASE sh -s" > "$OUT" <<'REMOTE'
set -eu

PROD_SLUG="$HA_PHASE3_PROD_SLUG"
BRIDGE_BASE="$HA_PHASE3_BRIDGE_BASE"
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

fetch_bridge_json() {
  route="$1"
  out="$2"
  : > "$out"
  if [ -n "$API_TOKEN" ]; then
    code=$(curl -sS --max-time 12 -H "api: $API_TOKEN" -o "$out" -w '%{http_code}' "$BRIDGE_BASE$route" 2>/dev/null || printf '000')
  else
    code=$(curl -sS --max-time 12 -o "$out" -w '%{http_code}' "$BRIDGE_BASE$route" 2>/dev/null || printf '000')
  fi
  printf '%s' "$code"
}

bool_true() {
  case "$(printf '%s' "$1" | tr '[:upper:]' '[:lower:]')" in
    true|1|yes|on) return 0 ;;
    *) return 1 ;;
  esac
}

INFO=$(curl -fsS -H "Authorization: Bearer $SUPERVISOR_TOKEN" "http://supervisor/addons/$PROD_SLUG/info" 2>/dev/null || true)
if [ -n "$INFO" ]; then
  STORED_API=$(printf '%s\n' "$INFO" | jq -r '.data.options.WB_API // .data.options.wb_api // ""' 2>/dev/null || true)
  WYZE_EMAIL=$(printf '%s\n' "$INFO" | jq -r '.data.options.WYZE_EMAIL // ""' 2>/dev/null || true)
  if [ -n "$STORED_API" ] && [ "$STORED_API" != "null" ]; then
    API_TOKEN="$STORED_API"
  elif [ -n "$WYZE_EMAIL" ] && [ "$WYZE_EMAIL" != "null" ]; then
    API_TOKEN=$(printf '%s' "$WYZE_EMAIL" | sha256sum | awk '{print $1}' | xxd -r -p | base64 | tr '+/' '-_' | tr -d '=\n' | cut -c1-40)
  fi
fi

section "Production Phase 3 SD_ONLY Probe"
echo "prod_slug=$PROD_SLUG"
echo "bridge_base=$BRIDGE_BASE" | redact
if [ -n "$API_TOKEN" ]; then echo "auth=api-header"; else echo "auth=none"; fi

section "Supervisor Selected Options"
printf '%s\n' "$INFO" \
  | jq -c '{slug:.data.slug,state:.data.state,repository:.data.repository,version:.data.version,SD_ONLY:(.data.options.SD_ONLY // ""),SNAPSHOT:(.data.options.SNAPSHOT // ""),GO2RTC_LAN_IP_OVERRIDES:(.data.options.GO2RTC_LAN_IP_OVERRIDES // "")}' 2>/dev/null \
  | redact || true

sd_only_option=$(printf '%s\n' "$INFO" | jq -r '.data.options.SD_ONLY // ""' 2>/dev/null || true)
if bool_true "$sd_only_option"; then
  echo "sd_only_option=true"
else
  echo "sd_only_option=false"
  mark_fail "production Supervisor option SD_ONLY must be true for Phase 3 production proof"
fi

section "Bridge Health"
health_body="/tmp/phase3-prod-health.json"
health_code=$(fetch_bridge_json "/health" "$health_body")
printf 'health_status=%s ' "$health_code"
cat "$health_body" 2>/dev/null | jq -c '{mtx_alive:(.mtx_alive // null),wyze_authed:(.wyze_authed // null),active_streams:(.active_streams // null)}' 2>/dev/null | redact || true
if [ "$health_code" != "200" ] || ! jq -e '.mtx_alive == true and .wyze_authed == true' "$health_body" >/dev/null 2>&1; then
  mark_fail "production health must report mtx_alive=true and wyze_authed=true"
fi

section "Catalog"
api_body="/tmp/phase3-prod-api.json"
api_code=$(fetch_bridge_json "/api" "$api_body")
camera_count=$(jq -r '(.cameras // {}) | length' "$api_body" 2>/dev/null || echo 0)
catalog_streams=$(jq -r '(.cameras // {}) | to_entries[] | select((.value.enabled // true) != false) | (.value.stream // .value.uri // .key)' "$api_body" 2>/dev/null | sort | tr '\n' ' ' | sed 's/ $//')
printf 'api_status=%s camera_count=%s catalog_streams=%s\n' "$api_code" "$camera_count" "${catalog_streams:-<none>}" | redact
if [ "$api_code" != "200" ] || [ "$camera_count" -le 0 ]; then
  mark_fail "authenticated production /api must return a non-empty camera catalog"
fi

configs_found=0
all_sd_only=true
all_one_feed=true
no_hd_supported=true
no_hd_enabled=true
enabled_count=0

section "Per-Camera Stream Config"
jq -r '(.cameras // {}) | to_entries[] | select((.value.enabled // true) != false) | .key | sub("-sub$"; "")' "$api_body" 2>/dev/null | while read -r cam; do
  [ -n "$cam" ] || continue
  config_file="/tmp/phase3-prod-${cam}.json"
  config_code=$(fetch_bridge_json "/api/$cam/stream-config" "$config_file")
  summary=$(jq -c --arg cam "$cam" '{camera:$cam,status_code:"'"$config_code"'",sd_only:(.sd_only // null),enabled_feeds:((.feeds // {}) | to_entries | map(select((.value.enabled // false) == true)) | map(.key)),hd_supported:((.feeds.hd.supported // false)),hd_enabled:((.feeds.hd.enabled // false)),sd_path:(.feeds.sd.path // null),sd_resolution:(.feeds.sd.resolution // null)}' "$config_file" 2>/dev/null || true)
  summary=$(printf '%s\n' "$summary" | sed 's/}$//')
  printf '%s\n' "${summary:-{\"camera\":\"$cam\",\"status_code\":\"$config_code\",\"error\":\"invalid-json\"}}" | redact
done > /tmp/phase3-prod-config-lines.jsonl

cat /tmp/phase3-prod-config-lines.jsonl

enabled_count=$(wc -l < /tmp/phase3-prod-config-lines.jsonl | tr -d ' ')
configs_found=$(jq -s '[.[] | select(.status_code == "200")] | length' /tmp/phase3-prod-config-lines.jsonl 2>/dev/null || echo 0)
if [ "$enabled_count" -eq 0 ] || [ "$configs_found" -ne "$enabled_count" ]; then
  mark_fail "every enabled production camera must return stream-config JSON"
fi
if jq -e 'select(.sd_only != true)' /tmp/phase3-prod-config-lines.jsonl >/dev/null 2>&1; then
  all_sd_only=false
  mark_fail "every production camera stream-config must report sd_only=true"
fi
if jq -e 'select((.enabled_feeds | length) != 1 or (.enabled_feeds[0] != "sd"))' /tmp/phase3-prod-config-lines.jsonl >/dev/null 2>&1; then
  all_one_feed=false
  mark_fail "every production camera must expose exactly one enabled SD feed"
fi
if jq -e 'select(.hd_supported == true)' /tmp/phase3-prod-config-lines.jsonl >/dev/null 2>&1; then
  no_hd_supported=false
  mark_fail "production SD_ONLY mode must report HD unsupported"
fi
if jq -e 'select(.hd_enabled == true)' /tmp/phase3-prod-config-lines.jsonl >/dev/null 2>&1; then
  no_hd_enabled=false
  mark_fail "production SD_ONLY mode must keep HD disabled"
fi

section "SD_ONLY Summary"
printf '{"camera_count":%s,"configs_found":%s,"all_sd_only":%s,"all_one_feed":%s,"no_hd_supported":%s,"no_hd_enabled":%s}\n' \
  "$enabled_count" "$configs_found" "$all_sd_only" "$all_one_feed" "$no_hd_supported" "$no_hd_enabled"

section "go2rtc Alias Proof"
details_file="/tmp/phase3-prod-details.json"
details_code=$(fetch_bridge_json "/health/details?stream=south-yard" "$details_file")
aliases=$(jq -r '(.go2rtc.aliases // .go2rtc.streams // [])[]?' "$details_file" 2>/dev/null | sort | tr '\n' ' ' | sed 's/ $//')
main_aliases=$(printf '%s\n' "$aliases" | tr ' ' '\n' | grep -Ev '(^$|-sd$)' || true)
only_sd_aliases=true
no_main_aliases=true
if [ -n "$main_aliases" ]; then
  only_sd_aliases=false
  no_main_aliases=false
  mark_fail "go2rtc must not expose native main aliases while production SD_ONLY is true"
fi
printf '{"details_status":"%s","aliases":"%s","only_sd_aliases":%s,"no_main_aliases":%s}\n' "$details_code" "${aliases:-<none>}" "$only_sd_aliases" "$no_main_aliases" | redact

section "Result"
if [ "$FAIL" -eq 0 ]; then
  echo "PASS: production Phase 3 SD_ONLY proof passed."
else
  echo "FAIL: production Phase 3 SD_ONLY proof failed."
fi

exit "$FAIL"
REMOTE
rc=$?
set -e

cat "$OUT"
printf 'artifact=%s\n' "$OUT"

exit "$rc"

#!/bin/sh
set -eu

# Minimal Home Assistant bridge swap helper.
#
# Use this when you need to test the local dev add-on against the live HA box
# without leaving production and dev running at the same time. The script keeps
# the flow simple: sync dev, copy prod options, stop one bridge, start the other,
# wait for /health, and optionally stop/restart Frigate around the handoff.

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
REPO_DIR=$(CDPATH= cd -- "$SCRIPT_DIR/.." && pwd)

CALLER_DEV_ADDON_SLUG=${HA_DEV_ADDON_SLUG-}
CALLER_PROD_ADDON_SLUG=${HA_PROD_ADDON_SLUG-}
CALLER_FRIGATE_ADDON_SLUG=${HA_FRIGATE_ADDON_SLUG-}

if [ -f "$SCRIPT_DIR/.ha_ssh.env" ]; then
  # shellcheck disable=SC1091
  . "$SCRIPT_DIR/.ha_ssh.env"
fi

[ -n "$CALLER_DEV_ADDON_SLUG" ] && HA_DEV_ADDON_SLUG=$CALLER_DEV_ADDON_SLUG
[ -n "$CALLER_PROD_ADDON_SLUG" ] && HA_PROD_ADDON_SLUG=$CALLER_PROD_ADDON_SLUG
[ -n "$CALLER_FRIGATE_ADDON_SLUG" ] && HA_FRIGATE_ADDON_SLUG=$CALLER_FRIGATE_ADDON_SLUG

DEV_SLUG="${HA_DEV_ADDON_SLUG:-docker_wyze_bridge_dev}"
PROD_SLUG="${HA_PROD_ADDON_SLUG:-docker_wyze_bridge_v4}"
FRIGATE_SLUG="${HA_FRIGATE_ADDON_SLUG:-ccab4aaf_frigate}"
PROD_INFO_FILE="$REPO_DIR/.orig_addon_info.json"
DEV_WEB_PORT="${HA_DEV_WEB_PORT:-55000}"
DEV_WHEP_PROXY_PORT="${HA_DEV_WHEP_PROXY_PORT:-18080}"
DEV_RTSP_PORT="${HA_DEV_RTSP_PORT:-28554}"
DEV_HLS_PORT="${HA_DEV_HLS_PORT:-28888}"
DEV_WEBRTC_PORT="${HA_DEV_WEBRTC_PORT:-28889}"
DEV_WEBRTC_UDP_PORT="${HA_DEV_WEBRTC_UDP_PORT:-28189}"
DEV_RTP_PORT="${HA_DEV_RTP_PORT:-28000}"
DEV_RTCP_PORT="${HA_DEV_RTCP_PORT:-28001}"
DEV_RTMP_PORT="${HA_DEV_RTMP_PORT:-21935}"
DEV_RTMPS_PORT="${HA_DEV_RTMPS_PORT:-21936}"
DEV_RTSPS_PORT="${HA_DEV_RTSPS_PORT:-28322}"
DEV_SRT_PORT="${HA_DEV_SRT_PORT:-28890}"
DEV_PLAYBACK_PORT="${HA_DEV_PLAYBACK_PORT:-29996}"
DEV_API_PORT="${HA_DEV_API_PORT:-29997}"
DEV_METRICS_PORT="${HA_DEV_METRICS_PORT:-29998}"
DEV_PPROF_PORT="${HA_DEV_PPROF_PORT:-29999}"

usage() {
  cat <<EOF
Usage: scripts/ha_dev_build.sh <command>

Commands:
  sync                Sync the local dev add-on tree and reload Supervisor metadata
  install             Sync the dev tree and install the dev add-on if needed
  status              Show a concise prod/dev status summary
  capture-prod        Save current production add-on info to $PROD_INFO_FILE
  copy-prod-options   Copy production add-on settings into the dev add-on
  swap-to-dev         Stop prod, sync/rebuild dev, start dev, and run a health smoke-check
  smoke-check         Verify the active bridge responds on health/UI endpoints
  restore-prod        Stop dev and restart production

Environment overrides:
  HA_DEV_ADDON_SLUG   default: $DEV_SLUG
  HA_PROD_ADDON_SLUG  default: $PROD_SLUG
  HA_DEV_SD_ONLY      when set to true/false, overrides SD_ONLY only for the dev add-on
EOF
}

ha_apps() {
  "$SCRIPT_DIR/ha_ssh.sh" ha apps "$@"
}

ha_supervisor() {
  "$SCRIPT_DIR/ha_ssh.sh" ha supervisor "$@"
}

ha_store() {
  "$SCRIPT_DIR/ha_ssh.sh" ha store "$@"
}

remote_supervisor_request() {
  method="$1"
  path="$2"
  "$SCRIPT_DIR/ha_ssh.sh" sh -s -- "$method" "$path" <<'EOF'
set -eu

method="$1"
path="$2"
tmp_body=$(mktemp)
cat >"$tmp_body"

cfg_file="$HOME/.homeassistant.yaml"
endpoint="${SUPERVISOR_ENDPOINT:-}"
token="${SUPERVISOR_TOKEN:-}"

if [ -f "$cfg_file" ]; then
  if [ -z "$endpoint" ]; then
    endpoint=$(sed -n 's/^endpoint:[[:space:]]*//p' "$cfg_file" | tail -n 1 | tr -d '"' | tr -d "'")
  fi
  if [ -z "$token" ]; then
    token=$(sed -n 's/^api-token:[[:space:]]*//p' "$cfg_file" | tail -n 1 | tr -d '"' | tr -d "'")
  fi
fi

if [ -z "$token" ]; then
  echo "Missing Supervisor API token. Set SUPERVISOR_TOKEN remotely or add api-token to ~/.homeassistant.yaml." >&2
  exit 1
fi

endpoint="${endpoint:-supervisor}"
case "$endpoint" in
  *://*) ;;
  *) endpoint="http://$endpoint" ;;
esac

if [ "$method" = "GET" ]; then
  curl -fsSL -X "$method" \
    -H "Authorization: Bearer $token" \
    -H "Content-Type: application/json" \
    "${endpoint%/}${path}"
else
  curl -fsSL -X "$method" \
    -H "Authorization: Bearer $token" \
    -H "Content-Type: application/json" \
    --data-binary @"$tmp_body" \
    "${endpoint%/}${path}"
  fi
EOF
}

remote_supervisor_post_json_file() {
  path="$1"
  local_json="$2"
  remote_tmp="/tmp/wyze_bridge_supervisor_payload_$$.json"
  KEY_PATH=$(eval printf '%s' "$HA_SSH_KEY")
  scp -P "${HA_SSH_PORT:-22}" -i "$KEY_PATH" "$local_json" "${HA_SSH_TARGET}:$remote_tmp" >/dev/null
  "$SCRIPT_DIR/ha_ssh.sh" sh -s -- "$path" "$remote_tmp" <<'EOF'
set -eu

path="$1"
tmp_body="$2"

cfg_file="$HOME/.homeassistant.yaml"
endpoint="${SUPERVISOR_ENDPOINT:-}"
token="${SUPERVISOR_TOKEN:-}"

if [ -f "$cfg_file" ]; then
  if [ -z "$endpoint" ]; then
    endpoint=$(sed -n 's/^endpoint:[[:space:]]*//p' "$cfg_file" | tail -n 1 | tr -d '"' | tr -d "'")
  fi
  if [ -z "$token" ]; then
    token=$(sed -n 's/^api-token:[[:space:]]*//p' "$cfg_file" | tail -n 1 | tr -d '"' | tr -d "'")
  fi
fi

if [ -z "$token" ]; then
  echo "Missing Supervisor API token. Set SUPERVISOR_TOKEN remotely or add api-token to ~/.homeassistant.yaml." >&2
  exit 1
fi

endpoint="${endpoint:-supervisor}"
case "$endpoint" in
  *://*) ;;
  *) endpoint="http://$endpoint" ;;
esac

curl -fsSL -X POST \
  -H "Authorization: Bearer $token" \
  -H "Content-Type: application/json" \
  --data-binary @"$tmp_body" \
  "${endpoint%/}${path}"
EOF
}

capture_addon_info() {
  slug="$1"
  dest="$2"
  remote_supervisor_request GET "/addons/$slug/info" </dev/null >"$dest"
}

addon_field() {
  slug="$1"
  field="$2"
  set +e
  info=$(ha_apps info "$slug" --raw-json 2>/dev/null)
  rc=$?
  set -e
  if [ $rc -ne 0 ]; then
    return $rc
  fi
  printf '%s' "$info" | python3 -c 'import json,sys; data=json.load(sys.stdin).get("data", {}); value=data.get(sys.argv[1], ""); print(value if value is not None else "")' "$field"
}

addon_web_port() {
  slug="$1"
  if [ "$slug" = "$DEV_SLUG" ]; then
    printf '%s\n' "$DEV_WEB_PORT"
    return 0
  fi
  info=$(ha_apps info "$slug" --raw-json 2>/dev/null || printf '')
  [ -n "$info" ] || return 1
  ADDON_INFO_JSON="$info" DEV_SLUG="$DEV_SLUG" DEV_WHEP_PROXY_PORT="$DEV_WHEP_PROXY_PORT" python3 - <<'PY'
import json
import os

root = json.loads(os.environ["ADDON_INFO_JSON"]).get("data", {})
network = root.get("network") or {}
descriptions = root.get("network_description") or {}

for key, host_port in network.items():
    if "Web UI" in descriptions.get(key, ""):
        print(host_port)
        raise SystemExit

fallback = network.get("5000/tcp")
if fallback:
    print(fallback)
    raise SystemExit

print("5000")
PY
}

addon_known() {
  addon_field "$1" name >/dev/null 2>&1
}

addon_installed() {
  installed=$(addon_field "$1" installed 2>/dev/null || printf '')
  version=$(addon_field "$1" version 2>/dev/null || printf '')
  [ "$installed" = "True" ] || [ "$installed" = "true" ] || [ -n "$version" ]
}

bridge_slots_summary() {
  "$SCRIPT_DIR/ha_ssh.sh" 'ha apps --raw-json 2>/dev/null | jq -r ".data.addons[]? | select((.slug|test(\"wyze|bridge\";\"i\")) or (.name|test(\"wyze|bridge\";\"i\"))) | [.slug,.name,.state,.repository,.version] | @tsv"' 2>/dev/null || true
}

wait_for_addon_state() {
  slug="$1"
  desired="$2"
  attempts="${3:-45}"
  delay="${4:-2}"

  i=1
  while [ "$i" -le "$attempts" ]; do
    state=$(addon_field "$slug" state 2>/dev/null || printf 'unavailable')
    if [ "$state" = "$desired" ]; then
      return 0
    fi
    sleep "$delay"
    i=$((i + 1))
  done

  echo "Add-on $slug did not reach state '$desired'." >&2
  return 1
}

wait_for_addon_not_state() {
  slug="$1"
  blocked="$2"
  attempts="${3:-45}"
  delay="${4:-2}"

  i=1
  while [ "$i" -le "$attempts" ]; do
    state=$(addon_field "$slug" state 2>/dev/null || printf 'unavailable')
    if [ "$state" != "$blocked" ]; then
      return 0
    fi
    sleep "$delay"
    i=$((i + 1))
  done

  echo "Add-on $slug remained in state '$blocked'." >&2
  return 1
}

wait_for_http() {
  url="$1"
  label="$2"
  attempts="${3:-45}"
  delay="${4:-2}"

  i=1
  while [ "$i" -le "$attempts" ]; do
    if "$SCRIPT_DIR/ha_ssh.sh" curl -fsS "$url" >/dev/null 2>&1; then
      return 0
    fi
    sleep "$delay"
    i=$((i + 1))
  done

  echo "$label did not respond at $url after $attempts attempts." >&2
  return 1
}

addon_base_url() {
  slug="$1"
  ip=$(addon_field "$slug" ip_address 2>/dev/null || printf '')
  port=$(addon_web_port "$slug" 2>/dev/null || printf '5000')
  if [ -z "$ip" ]; then
    echo "Could not determine IP address for add-on $slug." >&2
    return 1
  fi
  printf 'http://%s:%s' "$ip" "$port"
}

stop_addon_for_cutover() {
  slug="$1"
  state=$(addon_field "$slug" state 2>/dev/null || printf 'unavailable')
  if [ "$state" = "started" ]; then
    ha_apps stop "$slug" >/dev/null
    wait_for_addon_not_state "$slug" started
    return 0
  fi
  return 1
}

start_addon_best_effort() {
  slug="$1"
  label="$2"

  if ! addon_installed "$slug"; then
    return 0
  fi

  set +e
  ha_apps start "$slug" >/dev/null 2>&1
  rc=$?
  set -e

  if wait_for_addon_state "$slug" started 60 2 >/dev/null 2>&1; then
    return 0
  fi

  state=$(addon_field "$slug" state 2>/dev/null || printf 'unavailable')
  echo "Warning: $label did not return cleanly during cutover (start rc=$rc, state=$state)." >&2
  return 1
}

addon_ports() {
  slug="$1"
  info=$(ha_apps info "$slug" --raw-json 2>/dev/null || printf '')
  [ -n "$info" ] || return 0
  ADDON_INFO_JSON="$info" python3 - <<'PY'
import json
import os
import re

root = json.loads(os.environ["ADDON_INFO_JSON"]).get("data", {})
ports = set()

for value in (root.get("network") or {}).values():
    try:
        ports.add(int(value))
    except (TypeError, ValueError):
        pass

for entry in root.get("options", {}).get("MEDIAMTX") or []:
    if "=" not in entry:
        continue
    key, value = entry.split("=", 1)
    if "ADDRESS" not in key.upper():
        continue
    match = re.search(r":(\d+)$", value.strip())
    if match:
        ports.add(int(match.group(1)))

if root.get("slug") == os.environ.get("DEV_SLUG"):
    ports.add(int(os.environ.get("DEV_WHEP_PROXY_PORT", "18080")))
else:
    ports.add(8080)
print(" ".join(str(port) for port in sorted(ports)))
PY
}

busy_ports() {
  if [ "$#" -eq 0 ]; then
    return 0
  fi
  listening=$(
    "$SCRIPT_DIR/ha_ssh.sh" sh -c "ss -ltnu 2>/dev/null || netstat -ltnu 2>/dev/null" 2>/dev/null || printf ''
  )
  LISTENING_PORTS="$listening" python3 - "$@" <<'PY'
import os
import re
import sys

ports = [int(arg) for arg in sys.argv[1:] if arg]
text = os.environ.get("LISTENING_PORTS", "")
busy = []
for port in ports:
    if re.search(rf'[:.]%d(?:\s|$)' % port, text):
        busy.append(str(port))
print(" ".join(busy))
PY
}

wait_for_ports_free() {
  slug="$1"
  attempts="${2:-30}"
  delay="${3:-2}"
  ports=$(addon_ports "$slug" 2>/dev/null || printf '')
  [ -n "$ports" ] || return 0

  i=1
  while [ "$i" -le "$attempts" ]; do
    busy=$(busy_ports $ports)
    if [ -z "$busy" ]; then
      return 0
    fi
    sleep "$delay"
    i=$((i + 1))
  done

  echo "Timed out waiting for host-network ports to free for $slug. Busy ports: $busy" >&2
  return 1
}

sync_dev() {
  "$SCRIPT_DIR/deploy_ha_local_addon.sh" --target dev --no-rebuild
  store_log=$(mktemp)
  if ha_store reload >"$store_log" 2>&1; then
    printf '%s\n' "Home Assistant store metadata reloaded for local add-ons."
  else
    printf '%s\n' "Store reload failed; continuing to Supervisor metadata reload." >&2
    cat "$store_log" >&2
  fi
  reload_log=$(mktemp)
  if ha_supervisor reload >"$reload_log" 2>&1; then
    printf '%s\n' "Dev add-on source synced and Supervisor metadata reloaded."
    return 0
  fi

  if addon_known "$DEV_SLUG"; then
    printf '%s\n' "Dev add-on source synced. Supervisor metadata reload is unavailable on this HA, so the existing indexed dev slot will be reused." >&2
    cat "$reload_log" >&2
    return 0
  fi

  cat "$reload_log" >&2
  exit 1
}

install_dev() {
  sync_dev
  if addon_installed "$DEV_SLUG"; then
    printf '%s\n' "Dev add-on is already installed."
    return 0
  fi
  if ! addon_known "$DEV_SLUG"; then
    echo "Dev add-on is not indexed in Home Assistant yet. Either restore Supervisor reload support or point HA_DEV_ADDON_SLUG at an existing local add-on slot." >&2
    exit 1
  fi
  ha_apps install "$DEV_SLUG"
  printf '%s\n' "Dev add-on installed: $DEV_SLUG"
}

capture_prod() {
  capture_addon_info "$PROD_SLUG" "$PROD_INFO_FILE"
  printf '%s\n' "Saved production add-on info to $PROD_INFO_FILE"
}

copy_prod_options() {
  capture_prod
  payload_file=$(mktemp)
  DEV_API_PORT="$DEV_API_PORT" \
  DEV_HLS_PORT="$DEV_HLS_PORT" \
  DEV_METRICS_PORT="$DEV_METRICS_PORT" \
  DEV_PLAYBACK_PORT="$DEV_PLAYBACK_PORT" \
  DEV_PPROF_PORT="$DEV_PPROF_PORT" \
  DEV_RTCP_PORT="$DEV_RTCP_PORT" \
  DEV_RTMP_PORT="$DEV_RTMP_PORT" \
  DEV_RTMPS_PORT="$DEV_RTMPS_PORT" \
  DEV_RTP_PORT="$DEV_RTP_PORT" \
  DEV_RTSP_PORT="$DEV_RTSP_PORT" \
  DEV_RTSPS_PORT="$DEV_RTSPS_PORT" \
  DEV_SRT_PORT="$DEV_SRT_PORT" \
  DEV_WEBRTC_PORT="$DEV_WEBRTC_PORT" \
  DEV_WEBRTC_UDP_PORT="$DEV_WEBRTC_UDP_PORT" \
  HA_DEV_SD_ONLY="${HA_DEV_SD_ONLY:-}" \
  python3 - "$PROD_INFO_FILE" >"$payload_file" <<'PY'
import json
import os
from urllib.parse import urlparse
import sys

with open(sys.argv[1], "r", encoding="utf-8") as handle:
    root = json.load(handle)

data = root.get("data", {})
payload = data.get("options")

if not payload:
    raise SystemExit("Production add-on info did not include an options payload to copy.")

for key in ("WYZE_EMAIL", "WYZE_PASSWORD", "API_ID", "API_KEY", "TOTP_KEY"):
    value = payload.get(key)
    if isinstance(value, str):
        payload[key] = value.strip()


def pick_host(options):
    candidates = [
        options.get("DOMAIN"),
        options.get("WB_WEBRTC_URL"),
        options.get("WB_RTSP_URL"),
        options.get("WB_HLS_URL"),
        options.get("WB_RTMP_URL"),
    ]
    for candidate in candidates:
        if not candidate:
            continue
        if "://" in candidate:
            parsed = urlparse(candidate)
            if parsed.hostname:
                return parsed.hostname
        elif candidate.strip():
            return candidate.strip()
    return "homeassistant.local"


host = pick_host(payload)
payload["DOMAIN"] = host

for hidden_key in (
    "MEDIAMTX",
    "WB_RTSP_URL",
    "WB_WEBRTC_URL",
    "WB_HLS_URL",
    "WB_RTMP_URL",
    "WB_HLS_URL",
):
    payload.pop(hidden_key, None)

dev_sd_only = os.environ.get("HA_DEV_SD_ONLY", "").strip().lower()
if dev_sd_only:
    if dev_sd_only not in {"1", "true", "yes", "on", "0", "false", "no", "off"}:
        raise SystemExit("HA_DEV_SD_ONLY must be true or false when set.")
    payload["SD_ONLY"] = dev_sd_only in {"1", "true", "yes", "on"}

json.dump({"options": payload}, sys.stdout, separators=(",", ":"))
PY
  remote_supervisor_post_json_file "/addons/$DEV_SLUG/options" "$payload_file" >/dev/null
  printf '%s\n' "Copied production settings into $DEV_SLUG"
}

status() {
  prod_state=$(addon_field "$PROD_SLUG" state 2>/dev/null || printf 'unavailable')
  if addon_installed "$PROD_SLUG"; then
    prod_installed=True
  else
    prod_installed=False
  fi
  dev_state=$(addon_field "$DEV_SLUG" state 2>/dev/null || printf 'unavailable')
  if addon_installed "$DEV_SLUG"; then
    dev_installed=True
  else
    dev_installed=False
  fi
  cat <<EOF
Production:
  slug: $PROD_SLUG
  installed: $prod_installed
  state: $prod_state
Dev:
  slug: $DEV_SLUG
  installed: $dev_installed
  state: $dev_state
EOF
  bridge_slots=$(bridge_slots_summary)
  if [ -n "$bridge_slots" ]; then
    cat <<EOF
All bridge-like add-ons:
$bridge_slots
EOF
  fi
}

smoke_check() {
  dev_state=$(addon_field "$DEV_SLUG" state 2>/dev/null || printf 'unknown')
  if [ "$dev_state" != "started" ]; then
    echo "Dev add-on is not started (state=$dev_state)." >&2
    exit 1
  fi
  dev_base_url=$(addon_base_url "$DEV_SLUG")
  wait_for_http "$dev_base_url/health" "Dev add-on health endpoint"
  printf '%s\n' "Smoke check passed: health endpoint responded."
}

stop_addon_if_started() {
  slug="$1"
  state=$(addon_field "$slug" state 2>/dev/null || printf 'unavailable')
  if [ "$state" = "started" ] || [ "$state" = "error" ]; then
    ha_apps stop "$slug" >/dev/null
    if [ "$state" = "started" ]; then
      wait_for_addon_not_state "$slug" started
    fi
    sleep 10
  fi
  wait_for_ports_free "$slug"
}

swap_to_dev() {
  capture_prod
  install_dev
  copy_prod_options
  frigate_was_started=false
  if stop_addon_for_cutover "$FRIGATE_SLUG"; then
    frigate_was_started=true
  fi
  stop_addon_if_started "$DEV_SLUG"
  "$SCRIPT_DIR/deploy_ha_local_addon.sh" --target dev
  prod_was_started=$(addon_field "$PROD_SLUG" state 2>/dev/null || printf 'unavailable')
  rollback() {
    status=$?
    trap - EXIT INT TERM
  if [ $status -ne 0 ] && [ "$prod_was_started" = "started" ]; then
      echo "swap-to-dev failed; attempting to restore production..." >&2
      set +e
      stop_addon_if_started "$DEV_SLUG"
      ha_apps start "$PROD_SLUG" >/dev/null
      if [ "$frigate_was_started" = "true" ]; then
        start_addon_best_effort "$FRIGATE_SLUG" "Frigate"
      fi
      set -e
    fi
    exit $status
  }
  trap rollback EXIT INT TERM
  stop_addon_if_started "$PROD_SLUG"
  ha_apps start "$DEV_SLUG" >/dev/null
  wait_for_addon_state "$DEV_SLUG" started
  smoke_check
  if [ "$frigate_was_started" = "true" ]; then
    start_addon_best_effort "$FRIGATE_SLUG" "Frigate"
  fi
  trap - EXIT INT TERM
  printf '%s\n' "Dev build is active. Production remains stopped until restore-prod is run."
}

restore_prod() {
  frigate_was_started=false
  if stop_addon_for_cutover "$FRIGATE_SLUG"; then
    frigate_was_started=true
  fi
  stop_addon_if_started "$DEV_SLUG"
  ha_apps start "$PROD_SLUG" >/dev/null
  wait_for_addon_state "$PROD_SLUG" started
  prod_state=$(addon_field "$PROD_SLUG" state 2>/dev/null || printf 'unknown')
  if [ "$prod_state" != "started" ]; then
    echo "Production add-on did not return to started state (state=$prod_state)." >&2
    exit 1
  fi
  prod_base_url=$(addon_base_url "$PROD_SLUG")
  wait_for_http "$prod_base_url/health" "Production add-on health endpoint"
  if [ "$frigate_was_started" = "true" ]; then
    start_addon_best_effort "$FRIGATE_SLUG" "Frigate"
  fi
  printf '%s\n' "Production add-on restarted."
}

if [ $# -ne 1 ]; then
  usage >&2
  exit 1
fi

case "$1" in
  sync)
    sync_dev
    ;;
  install)
    install_dev
    ;;
  status)
    status
    ;;
  capture-prod)
    capture_prod
    ;;
  copy-prod-options)
    copy_prod_options
    ;;
  swap-to-dev)
    swap_to_dev
    ;;
  smoke-check)
    smoke_check
    ;;
  restore-prod)
    restore_prod
    ;;
  --help|-h|help)
    usage
    ;;
  *)
    usage >&2
    exit 1
    ;;
esac

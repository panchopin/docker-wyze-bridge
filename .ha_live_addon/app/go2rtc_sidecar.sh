#!/bin/sh

get_env_value() {
    var_name=$1
    eval "printf '%s' \"\${${var_name}:-}\""
}

set_env_if_empty_from_file() {
    var_name=$1
    file_path=$2
    if [ -n "$(get_env_value "${var_name}")" ] || [ ! -f "${file_path}" ]; then
        return
    fi
    value=$(cat "${file_path}" 2>/dev/null)
    export "${var_name}=${value}"
}

set_env_if_empty_from_options_json() {
    var_name=$1
    if [ -n "$(get_env_value "${var_name}")" ] || [ ! -f /data/options.json ]; then
        return
    fi
    value=$(python3 -c "import json, sys; data=json.load(open('/data/options.json')); print(str(data.get(sys.argv[1], '')).strip())" "${var_name}" 2>/dev/null)
    export "${var_name}=${value}"
}

load_go2rtc_runtime_env() {
    for key in WYZE_EMAIL WYZE_PASSWORD API_ID API_KEY; do
        set_env_if_empty_from_file "${key}" "/run/secrets/${key}"
        set_env_if_empty_from_options_json "${key}"
    done

    for key in WB_IP DOMAIN WB_RTSP_URL WB_WEBRTC_URL WB_HLS_URL GO2RTC_LAN_IP_OVERRIDES GO2RTC_FORCE_LAN_IP_OVERRIDES; do
        set_env_if_empty_from_options_json "${key}"
    done
}

go2rtc_sidecar_cleanup() {
    GO2RTC_CLEANUP_PID="${GO2RTC_PID:-}"
    if [ -f /tmp/go2rtc.pid ]; then
        GO2RTC_CLEANUP_PID=$(cat /tmp/go2rtc.pid 2>/dev/null)
    fi
    if [ -n "${GO2RTC_CLEANUP_PID}" ]; then
        kill "${GO2RTC_CLEANUP_PID}" 2>/dev/null || true
    fi
}

start_go2rtc_process() {
    nohup sh -c '
child=""
stop() {
    if [ -n "${child}" ]; then
        kill "${child}" 2>/dev/null || true
        wait "${child}" 2>/dev/null || true
    fi
    exit 0
}
trap stop TERM INT
while :; do
    go2rtc -config "${GO2RTC_CONFIG}" >> /tmp/go2rtc.log 2>&1 &
    child=$!
    wait "${child}"
    status=$?
    child=""
    echo "[GO2RTC] process exited status=${status}; restarting in 2s" >> /tmp/go2rtc.log
    sleep 2 &
    child=$!
    wait "${child}"
    child=""
done
' </dev/null >/dev/null 2>&1 &
    GO2RTC_PID=$!
    printf '%s\n' "${GO2RTC_PID}" > "${GO2RTC_PID_FILE}"
}

normalize_go2rtc_config() {
    if [ ! -f "${GO2RTC_CONFIG}" ]; then
        return
    fi

    python3 - <<'PY'
import os
from pathlib import Path


path = Path(os.environ["GO2RTC_CONFIG"])
if not path.exists():
    raise SystemExit(0)

lines = path.read_text(encoding="utf-8").splitlines()
managed = {"api", "rtsp", "webrtc"}
kept = []
i = 0

while i < len(lines):
    line = lines[i]
    if not line.startswith((" ", "\t")) and line.endswith(":") and line[:-1] in managed:
        i += 1
        while i < len(lines) and (not lines[i] or lines[i].startswith((" ", "\t"))):
            i += 1
        continue
    kept.append(line)
    i += 1

while kept and not kept[0].strip():
    kept.pop(0)

prefix = [
    "api:",
    f'  listen: ":{os.environ["GO2RTC_API_PORT"]}"',
    "rtsp:",
    f'  listen: ":{os.environ["GO2RTC_RTSP_PORT"]}"',
    "webrtc:",
    '  listen: "127.0.0.1:0"',
]

path.write_text("\n".join(prefix + kept).rstrip() + "\n", encoding="utf-8")
PY
}

preload_go2rtc_aliases() {
    if [ -z "${GO2RTC_API_BASE}" ]; then
        return
    fi

    python3 - <<'PY' | while IFS= read -r alias; do
import os
from pathlib import Path

path = Path(os.environ["GO2RTC_CONFIG"])
in_streams = False
for line in path.read_text(encoding="utf-8").splitlines():
    if line == "streams:":
        in_streams = True
        continue
    if in_streams and line and not line.startswith((" ", "\t")):
        break
    if not in_streams:
        continue
    if line.startswith("  ") and line.rstrip().endswith(":") and not line.startswith("    "):
        print(line.strip()[:-1])
PY
        [ -n "${alias}" ] || continue
        echo "[GO2RTC] Preloading native alias ${alias}" >&2
        curl -sf -X PUT "${GO2RTC_API_BASE}/api/preload?src=${alias}" >/dev/null 2>&1 || true
    done

    for attempt in 1 2 3 4 5; do
        sleep 2
        ready=$(curl -sf -X OPTIONS "${GO2RTC_API_BASE}/api/streams" 2>/dev/null | python3 -c "import json, sys; data = json.load(sys.stdin); print(','.join(sorted(name for name, details in data.items() if isinstance(details, dict) and details.get('producers'))))" 2>/dev/null || true)
        echo "[GO2RTC] Native preload readiness attempt ${attempt}/5 active=${ready:-none}" >&2
    done
}

start_go2rtc_preload_refresh_loop() {
    (
        while :; do
            sleep 60
            preload_go2rtc_aliases
        done
    ) &
}

start_go2rtc_sidecar() {
    if [ -x /config/go2rtc ] && ! command -v go2rtc >/dev/null 2>&1; then
        export PATH="/config:$PATH"
    fi

    load_go2rtc_runtime_env

    GO2RTC_BIN=$(command -v go2rtc 2>/dev/null || echo "NOT_FOUND")
    echo "[GO2RTC_DEBUG] binary=${GO2RTC_BIN} email_set=$([ -n "${WYZE_EMAIL}" ] && echo yes || echo no) secrets_dir=$(ls /run/secrets/ 2>/dev/null | tr '\n' ',' || echo NONE)" >&2

    trap go2rtc_sidecar_cleanup TERM INT

    if ! command -v go2rtc >/dev/null 2>&1 || [ -z "${WYZE_EMAIL}" ] || [ -z "${WYZE_PASSWORD}" ]; then
        return
    fi

    : "${GO2RTC_API_PORT:=11984}"
    : "${GO2RTC_RTSP_PORT:=19554}"
    : "${GO2RTC_CONFIG:=/config/go2rtc_wyze.yaml}"
    : "${GO2RTC_PID_FILE:=/tmp/go2rtc.pid}"
    : "${WB_APP_PORT:=5000}"
    GO2RTC_HAS_PERSISTED_STREAMS=0

    if [ ! -d /config ] && [ "${GO2RTC_CONFIG}" = "/config/go2rtc_wyze.yaml" ]; then
        GO2RTC_CONFIG=/tmp/go2rtc_wyze.yaml
    fi
    export GO2RTC_API_PORT GO2RTC_RTSP_PORT GO2RTC_CONFIG GO2RTC_PID_FILE WB_APP_PORT

    if [ -f "${GO2RTC_CONFIG}" ] && grep -A999 '^streams:$' "${GO2RTC_CONFIG}" | grep -q '^  [a-z0-9][a-z0-9_-]*:$'; then
        GO2RTC_HAS_PERSISTED_STREAMS=1
        echo "[GO2RTC] Preserving existing seeded config at ${GO2RTC_CONFIG}" >&2
    else
        python3 - <<'PY'
import json
import os
from pathlib import Path


def q(value: str) -> str:
    return json.dumps(value)


config = "\n".join(
    [
        "api:",
        f'  listen: ":{os.environ["GO2RTC_API_PORT"]}"',
        "rtsp:",
        f'  listen: ":{os.environ["GO2RTC_RTSP_PORT"]}"',
        "webrtc:",
        '  listen: "127.0.0.1:0"',
        "log:",
        "  level: info",
        "wyze:",
        f"  {q(os.environ['WYZE_EMAIL'])}:",
        f"    api_id: {q(os.environ.get('API_ID', ''))}",
        f"    api_key: {q(os.environ.get('API_KEY', ''))}",
        f"    password: {q(os.environ['WYZE_PASSWORD'])}",
        "streams:",
        "",
    ]
)

Path(os.environ["GO2RTC_CONFIG"]).write_text(config, encoding="utf-8")
PY
    fi

    normalize_go2rtc_config

    echo "[GO2RTC] Starting go2rtc HD sidecar (RTSP :${GO2RTC_RTSP_PORT}, API :${GO2RTC_API_PORT}) config=${GO2RTC_CONFIG}" >&2
    start_go2rtc_process

    (
        add_host_candidate() {
            candidate_value=$1
            if [ -z "${candidate_value}" ]; then
                return
            fi
            case " ${GO2RTC_HOST_CANDIDATES} " in
                *" ${candidate_value} "*) ;;
                *) GO2RTC_HOST_CANDIDATES="${GO2RTC_HOST_CANDIDATES} ${candidate_value}" ;;
            esac
        }

        url_host() {
            python3 -c "import sys, urllib.parse; print((urllib.parse.urlsplit(sys.argv[1]).hostname or '').strip())" "$1" 2>/dev/null
        }

        GO2RTC_API_BASE=""
        GO2RTC_HOST_CANDIDATES="127.0.0.1"
        add_host_candidate "${WB_IP}"
        add_host_candidate "${DOMAIN}"
        add_host_candidate "$(url_host "${WB_RTSP_URL:-}")"
        add_host_candidate "$(url_host "${WB_WEBRTC_URL:-}")"
        add_host_candidate "$(url_host "${WB_HLS_URL:-}")"
        HOSTNAME_IP=$(hostname -i 2>/dev/null | awk '{print $1}')
        add_host_candidate "${HOSTNAME_IP}"
        HOST_ROUTE_IP=$(python3 - <<'PY'
import socket
sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
try:
    sock.connect(("8.8.8.8", 53))
    print(sock.getsockname()[0])
finally:
    sock.close()
PY
)
        add_host_candidate "${HOST_ROUTE_IP}"

        for i in $(seq 1 40); do
            sleep 2
            for host in ${GO2RTC_HOST_CANDIDATES}; do
                candidate="http://${host}:${GO2RTC_API_PORT}"
                if curl -sf "${candidate}/api" > /dev/null 2>&1; then
                    GO2RTC_API_BASE="${candidate}"
                    echo "[GO2RTC] API ready after ${i}x2s via ${GO2RTC_API_BASE}" >&2
                    break 2
                fi
            done
        done
        if [ -z "${GO2RTC_API_BASE}" ]; then
            echo "[GO2RTC] WARNING: API did not become reachable on any candidate host (${GO2RTC_HOST_CANDIDATES})" >&2
            exit 0
        fi

        CAM_JSON=""
        for retry in $(seq 1 30); do
            CAM_JSON=$(curl -sf "${GO2RTC_API_BASE}/api/wyze?id=${WYZE_EMAIL}" 2>/dev/null)
            if [ -n "${CAM_JSON}" ] && [ "${CAM_JSON}" != "null" ] && [ "${CAM_JSON}" != "[]" ]; then
                break
            fi
            echo "[GO2RTC] /api/wyze not ready yet from ${GO2RTC_API_BASE} (attempt ${retry}/30), waiting 3s..." >&2
            sleep 3
        done
        if [ -z "${CAM_JSON}" ] || [ "${CAM_JSON}" = "null" ] || [ "${CAM_JSON}" = "[]" ]; then
            echo "[GO2RTC] WARNING: /api/wyze?id=${WYZE_EMAIL} still empty after retries - check credentials and camera list" >&2
            exit 0
        fi
        echo "[GO2RTC] Camera list received, refreshing native Wyze aliases..." >&2
        WB_APP_API_BASE=""
        BRIDGE_API_TOKEN=$(WYZE_EMAIL="${WYZE_EMAIL}" python3 - <<'PY'
import base64
import hashlib
import os
from pathlib import Path

email = os.environ.get("WYZE_EMAIL", "")
for path in ("/config/wb_api", "/tokens/wb_api", ".runtime/tokens/wb_api"):
    try:
        token = Path(path).read_text(encoding="utf-8").strip()
    except OSError:
        token = ""
    if token:
        print(token)
        raise SystemExit
print(base64.urlsafe_b64encode(hashlib.sha256(email.encode()).digest()).decode()[:40])
PY
)
        for retry in $(seq 1 30); do
            candidate="http://127.0.0.1:${WB_APP_PORT}"
            BRIDGE_API_PAYLOAD=$(curl -sf -H "api: ${BRIDGE_API_TOKEN}" "${candidate}/api" 2>/dev/null || true)
            if BRIDGE_API_PAYLOAD="${BRIDGE_API_PAYLOAD}" python3 - <<'PY'
import json
import os
import sys

try:
    payload = json.loads(os.environ.get("BRIDGE_API_PAYLOAD", ""))
except ValueError:
    sys.exit(1)
cameras = payload.get("cameras") if isinstance(payload, dict) else None
if isinstance(cameras, dict) and cameras:
    sys.exit(0)
sys.exit(1)
PY
            then
                WB_APP_API_BASE="${candidate}"
                echo "[GO2RTC] Bridge catalog ready after ${retry}x2s via ${WB_APP_API_BASE}" >&2
                break
            fi
            sleep 2
        done
        if [ -z "${WB_APP_API_BASE}" ]; then
            echo "[GO2RTC] WARNING: authenticated bridge catalog did not populate on http://127.0.0.1:${WB_APP_PORT}; keeping stale alias fallback and using helper-only alias filtering" >&2
        fi
        GO2RTC_CAM_JSON_FILE=/tmp/go2rtc_cam_sources.json
        printf '%s\n' "${CAM_JSON}" > "${GO2RTC_CAM_JSON_FILE}"
        GO2RTC_CONFIG="${GO2RTC_CONFIG}" GO2RTC_API_PORT="${GO2RTC_API_PORT}" GO2RTC_RTSP_PORT="${GO2RTC_RTSP_PORT}" GO2RTC_CAM_JSON_FILE="${GO2RTC_CAM_JSON_FILE}" WB_APP_API_BASE="${WB_APP_API_BASE}" WYZE_EMAIL="${WYZE_EMAIL}" API_ID="${API_ID}" API_KEY="${API_KEY}" WYZE_PASSWORD="${WYZE_PASSWORD}" python3 - <<'PY'
import base64
import hashlib
import ipaddress
import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path


def q(value: str) -> str:
    return json.dumps(value)


def clean_cam_name(name: str, uri_sep: str = "-") -> str:
    return re.sub(r"[^-\w+]", "", name.strip().replace(" ", uri_sep)).encode("ascii", "ignore").decode().lower()


def with_subtype(url: str, subtype: str) -> str:
    parsed = urllib.parse.urlsplit(url)
    query = urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)
    filtered = [(key, value) for key, value in query if key != "subtype"]
    filtered.append(("subtype", subtype))
    return urllib.parse.urlunsplit(parsed._replace(query=urllib.parse.urlencode(filtered)))


def normalize_mac(value: str) -> str:
    return re.sub(r"[^0-9A-F]", "", str(value or "").upper())


def lan_ip_overrides() -> dict[str, str]:
    overrides = {}
    raw = os.environ.get("GO2RTC_LAN_IP_OVERRIDES", "")
    if not raw:
        try:
            with open("/data/options.json", encoding="utf-8") as fh:
                options = json.load(fh)
            raw = str(options.get("GO2RTC_LAN_IP_OVERRIDES") or "")
        except (OSError, ValueError, TypeError):
            raw = ""
    for item in raw.split(","):
        if "=" not in item:
            continue
        mac, host = item.split("=", 1)
        mac = normalize_mac(mac)
        host = host.strip()
        if mac and host:
            overrides[mac] = host
    if overrides:
        print(f"[GO2RTC] LAN IP overrides loaded for {len(overrides)} camera(s)", flush=True)
    return overrides


def camera_mac(cam: dict) -> str:
    value = cam.get("mac") or cam.get("mac_address")
    if value:
        return normalize_mac(value)
    parsed = urllib.parse.urlsplit(str(cam.get("url") or ""))
    query = urllib.parse.parse_qs(parsed.query)
    for key in ("mac", "mac_address"):
        values = query.get(key) or []
        if values:
            return normalize_mac(values[0])
    for part in str(cam.get("info") or "").split("|"):
        candidate = normalize_mac(part)
        if len(candidate) == 12:
            return candidate
    return ""


def is_private_lan_host(host: str) -> bool:
    try:
        ip = ipaddress.ip_address(str(host or "").strip())
    except ValueError:
        return False
    return ip.is_private


def force_lan_ip_overrides() -> bool:
    return str(os.environ.get("GO2RTC_FORCE_LAN_IP_OVERRIDES", "")).strip().lower() in {"1", "true", "yes", "on"}


def with_lan_ip_override(url: str, cam: dict) -> str:
    ip = lan_ip_overrides().get(camera_mac(cam))
    if not ip:
        return url
    parsed = urllib.parse.urlsplit(url)
    if is_private_lan_host(parsed.hostname or "") and not force_lan_ip_overrides():
        print(
            f"[GO2RTC] LAN override for {cam.get('name', '<unknown>')} is configured, "
            f"but keeping helper LAN host {parsed.hostname}; set GO2RTC_FORCE_LAN_IP_OVERRIDES=true to force it",
            flush=True,
        )
        return url
    return urllib.parse.urlunsplit(parsed._replace(netloc=ip))


def parse_model(info: str, url: str) -> str:
    if info:
        model = str(info).split("|", 1)[0].strip()
        if model:
            return model
    parsed = urllib.parse.urlsplit(url)
    query = urllib.parse.parse_qs(parsed.query)
    return (query.get("model") or [""])[0].strip()


def helper_flag(cam: dict, key: str):
    if key not in cam:
        return None
    value = cam.get(key)
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def bridge_api_token(email: str) -> str:
    for path in ("/config/wb_api", "/tokens/wb_api", ".runtime/tokens/wb_api"):
        try:
            token = Path(path).read_text(encoding="utf-8").strip()
        except OSError:
            token = ""
        if token:
            return token
    return base64.urlsafe_b64encode(hashlib.sha256(email.encode()).digest()).decode()[:40]


def fetch_json(url: str, timeout: float = 2.0, api_token: str = ""):
    try:
        request = urllib.request.Request(url)
        if api_token:
            request.add_header("api", api_token)
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.load(response)
    except (OSError, ValueError, urllib.error.HTTPError, urllib.error.URLError):
        return None


_BRIDGE_CAMERA_CATALOG = None


def bridge_camera_catalog() -> dict | None:
    global _BRIDGE_CAMERA_CATALOG
    if _BRIDGE_CAMERA_CATALOG is not None:
        return _BRIDGE_CAMERA_CATALOG

    base_url = os.environ.get("WB_APP_API_BASE", "").rstrip("/")
    if not base_url:
        return None

    api_token = bridge_api_token(os.environ["WYZE_EMAIL"])
    payload = fetch_json(f"{base_url}/api", api_token=api_token)
    if not isinstance(payload, dict):
        return None
    cameras = payload.get("cameras") if isinstance(payload, dict) else None
    _BRIDGE_CAMERA_CATALOG = cameras if isinstance(cameras, dict) else {}
    return _BRIDGE_CAMERA_CATALOG


def bridge_published_entries(cam_uri: str):
    catalog = bridge_camera_catalog()
    if catalog is None:
        return None

    published = []
    for uri, camera in catalog.items():
        if not isinstance(camera, dict):
            continue
        base_uri = clean_cam_name(camera.get("camera_uri") or camera.get("name_uri") or "")
        if base_uri == cam_uri:
            published.append((uri, camera))
    return published


def bridge_camera_state(cam_uri: str) -> dict:
    base_url = os.environ.get("WB_APP_API_BASE", "").rstrip("/")
    if not base_url:
        return {}

    api_token = bridge_api_token(os.environ["WYZE_EMAIL"])
    cam_path = urllib.parse.quote(cam_uri, safe="")
    state = {}

    catalog = bridge_camera_catalog()
    published = bridge_published_entries(cam_uri)
    bridge_catalog_empty = isinstance(catalog, dict) and not catalog
    if bridge_catalog_empty:
        published = None
    if published is not None:
        enabled_entries = [(uri, camera) for uri, camera in published if bool(camera.get("enabled"))]
        state["published"] = bool(enabled_entries)
        state["enabled"] = bool(enabled_entries)
        state["hd"] = any(
            clean_cam_name(camera.get("name_uri") or uri) == cam_uri
            and not bool(camera.get("substream"))
            for uri, camera in enabled_entries
        )
        state["sd"] = any(
            bool(camera.get("substream")) or clean_cam_name(camera.get("name_uri") or uri) != cam_uri
            for uri, camera in enabled_entries
        )

    config = fetch_json(f"{base_url}/api/{cam_path}/stream-config", api_token=api_token)
    feeds = config.get("feeds") if isinstance(config, dict) else None
    if isinstance(config, dict) and config.get("native_preview_sd"):
        state["sd"] = True
        state["sd_supported"] = True
    if isinstance(feeds, dict):
        sd_only = bool(config.get("sd_only")) if isinstance(config, dict) else False
        for feed_name in ("hd", "sd"):
            feed = feeds.get(feed_name)
            if not isinstance(feed, dict):
                continue
            if "enabled" in feed:
                if sd_only:
                    state[feed_name] = bool(feed.get("enabled"))
                elif published is None or feed.get("path") == "native":
                    state[feed_name] = feed.get("enabled")
                elif not state.get(feed_name, False):
                    state[feed_name] = False
            if "supported" in feed:
                state[f"{feed_name}_supported"] = feed.get("supported")
    if "enabled" not in state:
        state["enabled"] = bool(state.get("hd") or state.get("sd"))
    elif not state.get("enabled") and (state.get("hd") or state.get("sd")):
        state["enabled"] = True
    return state


with open(os.environ["GO2RTC_CAM_JSON_FILE"], encoding="utf-8") as fh:
    data = json.load(fh)
cams = data.get("sources", data) if isinstance(data, dict) else data
lines = [
    "api:",
    f'  listen: ":{os.environ["GO2RTC_API_PORT"]}"',
    "rtsp:",
    f'  listen: ":{os.environ["GO2RTC_RTSP_PORT"]}"',
    "webrtc:",
    '  listen: "127.0.0.1:0"',
    "log:",
    "  level: info",
    "wyze:",
    f"  {q(os.environ['WYZE_EMAIL'])}:",
    f"    api_id: {q(os.environ.get('API_ID', ''))}",
    f"    api_key: {q(os.environ.get('API_KEY', ''))}",
    f"    password: {q(os.environ['WYZE_PASSWORD'])}",
    "streams:",
]

added = 0
seen = set()
for cam in cams:
    name = cam.get("name", "")
    url = cam.get("url", "")
    info = cam.get("info", "")
    if not name or not url:
        continue
    uri = clean_cam_name(name)
    if not uri or uri in seen:
        continue
    seen.add(uri)
    bridge_state = bridge_camera_state(uri)
    for key, value in bridge_state.items():
        cam.setdefault(key, value)
    published = helper_flag(cam, "published")
    if published is False and helper_flag(cam, "hd") is False and helper_flag(cam, "sd") is False:
        print(f"[GO2RTC] Skipping camera not published by bridge: {name}", flush=True)
        continue
    enabled = helper_flag(cam, "enabled")
    if enabled is False:
        print(f"[GO2RTC] Skipping disabled camera from helper: {name}", flush=True)
        continue
    model = parse_model(info, url)
    hd_enabled = helper_flag(cam, "hd")
    sd_enabled = helper_flag(cam, "sd")
    hd_supported = helper_flag(cam, "hd_supported")
    sd_supported = helper_flag(cam, "sd_supported")

    if hd_supported is None and model == "HL_BC":
        hd_supported = False
    if sd_supported is None and model == "HL_BC":
        sd_supported = True

    aliases = []
    if hd_enabled is not False and hd_supported is not False:
        aliases.append((uri, "hd"))
    if sd_enabled is not False and sd_supported is not False:
        aliases.append((f"{uri}-sd", "sd"))

    if not aliases:
        print(f"[GO2RTC] Skipping camera with no enabled native feeds: {name} ({info})", flush=True)
        continue

    for alias, subtype in aliases:
        lines.append(f"  {alias}:")
        lines.append(f"    - {with_subtype(with_lan_ip_override(url, cam), subtype)}")
        print(f"[GO2RTC] Prepared stream: {alias} ({info}) subtype={subtype}", flush=True)
        added += 1

Path(os.environ["GO2RTC_CONFIG"]).write_text("\n".join(lines) + "\n", encoding="utf-8")
print(f"[GO2RTC] Total aliases prepared in config: {added}", flush=True)
PY
        echo "[GO2RTC] Restarting sidecar with direct DTLS helper URLs" >&2
        kill "${GO2RTC_PID}" 2>/dev/null || true
        wait "${GO2RTC_PID}" 2>/dev/null || true
        start_go2rtc_process
        sleep 5
        preload_go2rtc_aliases
        start_go2rtc_preload_refresh_loop
        curl -sf -X OPTIONS "${GO2RTC_API_BASE}/api/streams" 2>/dev/null | python3 -c "
import json
import sys

data = json.load(sys.stdin)
active = sorted(name for name, details in data.items() if details.get('producers'))
print(f'[GO2RTC] Active producer aliases: {active}', flush=True)
" >&2 || echo "[GO2RTC] WARNING: could not confirm active producer aliases yet" >&2
    ) &
}

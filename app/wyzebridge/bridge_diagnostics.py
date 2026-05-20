import os
from pathlib import Path
from urllib.parse import quote

import requests

from wyzebridge.bridge_utils import env_bool
from wyzebridge.go2rtc import go2rtc_probe

DEFAULT_MEDIAMTX_API_PORT = 9997
DEFAULT_WHEP_PROXY_PORT = int(os.getenv("WHEP_PROXY_PORT", "8080"))


def _http_base(address: str | None, default_port: int) -> str:
    value = (address or "").strip()
    if not value:
        return f"http://127.0.0.1:{default_port}"
    if value.startswith(("http://", "https://")):
        return value.rstrip("/")
    if value.startswith(":"):
        return f"http://127.0.0.1{value}".rstrip("/")
    if value.startswith("[") or value.count(":") == 1:
        return f"http://{value}".rstrip("/")
    return f"http://{value}:{default_port}".rstrip("/")


def _probe_json(url: str, timeout: float = 1.5) -> dict:
    result = {"url": url, "reachable": False}
    try:
        response = requests.get(url, timeout=timeout)
        result["status_code"] = response.status_code
        response.raise_for_status()
        result["reachable"] = True
        try:
            result["data"] = response.json()
        except ValueError:
            body = response.text.strip()
            if body:
                result["body"] = body[:512]
    except requests.RequestException as ex:
        if ex.response is not None:
            result["status_code"] = ex.response.status_code
        result["error"] = str(ex)
    return result


def whep_proxy_probe(stream_name: str | None, timeout: float = 1.5) -> dict:
    listener = _http_base(None, DEFAULT_WHEP_PROXY_PORT)
    if not stream_name:
        return {
            "listener": listener,
            "reachable": None,
            "error": "stream parameter required",
        }
    probe = _probe_json(
        f"{listener}/status/{quote(stream_name, safe='')}", timeout=timeout
    )
    probe["listener"] = listener
    return probe


def mediamtx_probe(stream_name: str | None, timeout: float = 1.5) -> dict:
    listener = _http_base(os.getenv("MTX_APIADDRESS"), DEFAULT_MEDIAMTX_API_PORT)
    if not env_bool("MTX_API", style="bool"):
        return {
            "listener": listener,
            "enabled": False,
            "reachable": None,
            "error": "MediaMTX Control API disabled (set MTX_API=true to enable)",
        }

    if stream_name:
        probe = _probe_json(
            f"{listener}/v3/paths/get/{quote(stream_name, safe='')}", timeout=timeout
        )
    else:
        probe = _probe_json(f"{listener}/v3/paths/list", timeout=timeout)
    probe["listener"] = listener
    probe["enabled"] = True
    return probe


def _tail_file(path: str, max_lines: int = 160) -> dict:
    result = {"path": path, "exists": False, "lines": []}
    log_path = Path(path)
    try:
        if not log_path.exists():
            return result
        result["exists"] = True
        result["lines"] = log_path.read_text(errors="replace").splitlines()[-max_lines:]
    except OSError as ex:
        result["error"] = str(ex)
    return result


def collect_bridge_diagnostics(
    stream_name: str | None = None, stream_info: dict | None = None
) -> dict:
    diagnostics = {
        "stream": stream_name,
        "whep_proxy": whep_proxy_probe(stream_name),
        "mediamtx": mediamtx_probe(stream_name),
    }
    include_streams = bool(stream_info and stream_info.get("native_alias"))
    diagnostics["go2rtc"] = go2rtc_probe(include_streams=include_streams)
    diagnostics["go2rtc"]["log_tail"] = _tail_file("/tmp/go2rtc.log")
    diagnostics["whep_proxy"]["log_tail"] = _tail_file("/tmp/whep_proxy.log")
    if stream_info:
        diagnostics["go2rtc"]["selection"] = {
            "supported": stream_info.get("native_supported"),
            "selected": stream_info.get("native_selected"),
            "reason": stream_info.get("native_reason"),
            "preload": stream_info.get("native_preload"),
            "snapshot_source": stream_info.get("snapshot_source"),
            "talkback_supported": stream_info.get("talkback_supported"),
            "talkback_reason": stream_info.get("talkback_reason"),
            "talkback_source": stream_info.get("talkback_source"),
        }
        alias = stream_info.get("native_alias")
        if alias:
            aliases = diagnostics["go2rtc"].get("aliases")
            diagnostics["go2rtc"]["alias"] = {
                "name": alias,
                "exists": alias in aliases if isinstance(aliases, list) else None,
            }
        talkback_alias = stream_info.get("talkback_alias")
        if talkback_alias:
            aliases = diagnostics["go2rtc"].get("aliases")
            diagnostics["go2rtc"]["talkback_alias"] = {
                "name": talkback_alias,
                "exists": talkback_alias in aliases if isinstance(aliases, list) else None,
            }
    return diagnostics

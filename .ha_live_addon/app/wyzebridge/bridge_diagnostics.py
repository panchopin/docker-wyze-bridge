import os
from urllib.parse import quote

import requests

from wyzebridge.bridge_utils import env_bool

DEFAULT_MEDIAMTX_API_PORT = 9997
DEFAULT_WHEP_PROXY_PORT = 8080


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


def collect_bridge_diagnostics(stream_name: str | None = None) -> dict:
    return {
        "stream": stream_name,
        "whep_proxy": whep_proxy_probe(stream_name),
        "mediamtx": mediamtx_probe(stream_name),
    }

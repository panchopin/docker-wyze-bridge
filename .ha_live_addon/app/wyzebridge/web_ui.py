import json
import os
from time import sleep
from typing import Callable, Generator, Optional
from urllib.parse import urlparse, urlunparse

from flask import request
from flask import url_for as _url_for
from flask_httpauth import HTTPBasicAuth
from werkzeug.security import check_password_hash

from wyzebridge.config import (
    BRIDGE_IP,
    HASS_TOKEN,
    IMG_PATH,
    IMG_TYPE,
    LLHLS,
    RTMP_URL,
    RTSP_URL,
    SNAPSHOT_TYPE,
    TOKEN_PATH,
    WEBRTC_URL,
    HLS_URL,
)
from wyzebridge.auth import WbAuth
from wyzebridge.bridge_utils import env_bool
from wyzebridge.logging import logger
from wyzebridge.preview_validation import preview_file_is_image
from wyzebridge.stream import Stream
from wyzebridge.stream_manager import StreamManager

auth = HTTPBasicAuth()

API_ENDPOINTS = "/api", "/img", "/snapshot", "/thumb", "/photo"


@auth.verify_password
def verify_password(username, password):
    if HASS_TOKEN and request.remote_addr == "172.30.32.2":
        return True
    if WbAuth.api in (request.args.get("api"), request.headers.get("api")):
        return request.path.startswith(API_ENDPOINTS)
    if username == WbAuth.username:
        return check_password_hash(WbAuth.hashed_password(), password)
    return not WbAuth.enabled


@auth.error_handler
def unauthorized():
    return {"error": "Unauthorized"}, 401


def url_for(endpoint, **values):
    proxy = (
        request.headers.get("X-Ingress-Path")
        or request.headers.get("X-Forwarded-Prefix")
        or ""
    ).rstrip("/")
    return proxy + _url_for(endpoint, **values)


def sse_generator(sse_status: Callable) -> Generator[str, str, str]:
    """Generator to return the status for enabled cameras."""
    cameras = {}
    while True:
        if cameras != (cameras := sse_status()):
            yield f"data: {json.dumps(cameras)}\n\n"
        sleep(1)


def mfa_generator(mfa_req: Callable) -> Generator[str, str, str]:
    if mfa_req():
        yield f"event: mfa\ndata: {mfa_req()}\n\n"
        while mfa_req():
            sleep(1)
    while True:
        yield "event: mfa\ndata: clear\n\n"
        sleep(30)


def set_mfa(mfa_code: str) -> bool:
    """Set MFA code from WebUI."""
    mfa_file = f"{TOKEN_PATH}mfa_token.txt"
    try:
        with open(mfa_file, "w") as f:
            f.write(mfa_code)
        while os.path.getsize(mfa_file) != 0:
            sleep(1)
        return True
    except Exception as ex:
        logger.error(ex)
        return False


def get_webrtc_signal(cam_name: str, api_key: str) -> dict:
    """Generate signaling for MediaMTX webrtc."""
    hostname = env_bool("DOMAIN", urlparse(request.root_url).hostname or "localhost")
    ssl = "s" if env_bool("MTX_WEBRTCENCRYPTION") else ""
    webrtc = WEBRTC_URL.lstrip("http") or f"{ssl}://{hostname}:8889"
    wep = {"result": "ok", "cam": cam_name, "whep": f"http{webrtc}/{cam_name}/whep"}

    if ice_server := validate_ice(env_bool("MTX_WEBRTCICESERVERS")):
        return wep | {"servers": ice_server}

    ice_server = {
        "credentialType": "password",
        "urls": ["stun:stun.l.google.com:19302"],
    }
    if api_key:
        ice_server |= {
            "username": "wb",
            "credential": api_key,
            "credentialType": "password",
        }
    return wep | {"servers": [ice_server]}


def validate_ice(data: str) -> Optional[list[dict]]:
    if not data:
        return
    try:
        json_data = json.loads(data)
        if "urls" in json_data:
            return [json_data]
    except ValueError:
        return


def preview_refresh_route(snapshot_type: str) -> str:
    return "thumb" if snapshot_type == "api" else "snapshot"


def _with_scheme(url: Optional[str], scheme: str) -> Optional[str]:
    if not url:
        return url
    parsed = urlparse(url)
    if not parsed.netloc:
        return url
    return urlunparse(parsed._replace(scheme=scheme))


def _normalized_hls(url: Optional[str]) -> Optional[str]:
    return (
        _with_scheme(url, "https" if LLHLS else urlparse(url).scheme or "http")
        if url
        else url
    )


def _mtx_port(env_name: str, default: str) -> str:
    address = str(env_bool(env_name, default, style="original") or default).strip()
    if ":" in address:
        return address.rsplit(":", 1)[-1]
    return address or default.strip(":")


def _replace_url_host(url: Optional[str], hostname: str) -> Optional[str]:
    if not url:
        return url
    parsed = urlparse(url)
    if not parsed.netloc:
        return url
    netloc = hostname
    if parsed.port:
        netloc = f"{hostname}:{parsed.port}"
    return urlunparse(parsed._replace(netloc=netloc))


def _lan_base_from_request(default_scheme: str) -> str:
    hostname = env_bool("DOMAIN", urlparse(request.root_url).hostname or "localhost")
    return f"{default_scheme}://{hostname}"


def _stream_entry(
    stream_id: str,
    label: str,
    external_url: Optional[str],
    lan_url: Optional[str],
    available: bool,
    reason: str,
) -> dict:
    url = external_url
    lan = lan_url
    return {
        "id": stream_id,
        "label": label,
        "url": url,
        "lan_url": lan if lan and lan != url else None,
        "available": bool(available and url),
        "reason": "" if available and url else reason,
        "auth_required": bool(WbAuth.api),
        "copy_text": url,
        "lan_copy_text": lan if lan and lan != url else None,
    }


def _evaluate_stream(requirements: list[tuple[bool, str]]) -> tuple[bool, str]:
    for condition, reason in requirements:
        if not condition:
            return False, reason
    return True, ""


def _prefer_stream_urls(
    external_url: Optional[str], lan_url: Optional[str]
) -> tuple[Optional[str], Optional[str]]:
    if external_url:
        return external_url, lan_url if lan_url and lan_url != external_url else None
    return lan_url, None


def _evaluate_on_demand_stream(
    enabled: bool, primary_url: Optional[str], offline_reason: str = ""
) -> tuple[bool, str]:
    if not enabled:
        return False, "disabled"
    if not primary_url:
        return False, "not available"
    return True, offline_reason if False else ""


def build_stream_entries(camera: dict, data: dict) -> list[dict]:
    enabled = camera.get("enabled", False)
    connected = camera.get("connected", False)
    active_reason = "disabled" if not enabled else "offline"
    lan_base = env_bool("DOMAIN", urlparse(request.root_url).hostname or "localhost")

    hls_base = camera.get("hls_url") if "hls_url" in camera else data.get("hls_url")
    webrtc_base = camera.get("webrtc_url") if "webrtc_url" in camera else data.get("webrtc_url")
    external_hls = _normalized_hls(f"{hls_base}stream.m3u8") if hls_base else None
    external_webrtc = f"{webrtc_base}whep" if webrtc_base else None
    external_rtmp = camera.get("rtmp_url") if "rtmp_url" in camera else data.get("rtmp_url")
    external_rtsp = camera.get("rtsp_url") if "rtsp_url" in camera else data.get("rtsp_url")
    if camera.get("native_selected") and camera.get("native_rtsp_url"):
        external_rtsp = _replace_url_host(camera.get("native_rtsp_url"), lan_base)
    external_fw_rtsp = (
        f"{external_rtsp}fw"
        if camera.get("rtsp_fw_enabled") and external_rtsp
        else None
    )

    lan_webrtc = (
        f"http://{lan_base}:{_mtx_port('MTX_WEBRTCADDRESS', ':8889')}/{camera['uri']}/whep"
    )
    lan_hls = (
        f"https://{lan_base}:{_mtx_port('MTX_HLSADDRESS', ':8888')}/{camera['uri']}/stream.m3u8"
    )
    lan_rtmp = f"rtmp://{lan_base}:51935/{camera['uri']}"
    lan_rtsp = f"rtsp://{lan_base}:58554/{camera['uri']}"
    if camera.get("native_selected") and camera.get("native_rtsp_url"):
        lan_rtsp = _replace_url_host(camera.get("native_rtsp_url"), lan_base)
    lan_fw_rtsp = f"{lan_rtsp}fw" if camera.get("rtsp_fw_enabled") else None

    external_webrtc_url, lan_webrtc_url = _prefer_stream_urls(
        external_webrtc, lan_webrtc
    )
    webrtc_available, webrtc_reason = _evaluate_stream(
        [
            (bool(camera.get("webrtc")), "not supported"),
            (bool(external_webrtc), "not configured"),
            (enabled, active_reason),
            (connected, active_reason),
        ]
    )
    external_rtmp_url, lan_rtmp_url = _prefer_stream_urls(external_rtmp, lan_rtmp)
    rtmp_available, rtmp_reason = _evaluate_on_demand_stream(enabled, external_rtmp_url)
    external_rtsp_url, lan_rtsp_url = _prefer_stream_urls(external_rtsp, lan_rtsp)
    rtsp_available, rtsp_reason = _evaluate_on_demand_stream(enabled, external_rtsp_url)
    external_fw_rtsp_url, lan_fw_rtsp_url = _prefer_stream_urls(
        external_fw_rtsp, lan_fw_rtsp
    )
    fw_rtsp_available, fw_rtsp_reason = _evaluate_stream(
        [
            (bool(camera.get("rtsp_fw_enabled")), "not supported"),
            (enabled, active_reason),
            (connected, active_reason),
            (bool(external_fw_rtsp_url), "not available"),
        ]
    )

    streams = [
        _stream_entry(
            "webrtc",
            "WebRTC",
            external_webrtc_url,
            lan_webrtc_url,
            webrtc_available,
            webrtc_reason,
        ),
        _stream_entry(
            "hls",
            "HLS",
            external_hls,
            lan_hls,
            False,
            "direct playlist unavailable" if HLS_URL else "not configured",
        ),
        _stream_entry(
            "rtmp",
            "RTMP",
            external_rtmp_url,
            lan_rtmp_url,
            rtmp_available,
            rtmp_reason,
        ),
        _stream_entry(
            "rtsp",
            "RTSP",
            external_rtsp_url,
            lan_rtsp_url,
            rtsp_available,
            rtsp_reason,
        ),
        _stream_entry(
            "fw_rtsp",
            "FW_RTSP",
            external_fw_rtsp_url,
            lan_fw_rtsp_url,
            fw_rtsp_available,
            fw_rtsp_reason,
        ),
        _stream_entry(
            "sd_card",
            "SD Card",
            camera.get("boa_url"),
            None,
            bool(camera.get("boa_url")) and connected,
            "not supported" if not camera.get("boa_url") else active_reason,
        ),
        _stream_entry(
            "rtsp_snapshot",
            "RTSP Snapshot",
            data.get("snapshot_url"),
            None,
            SNAPSHOT_TYPE != "api" and enabled,
            "disabled in api mode" if SNAPSHOT_TYPE == "api" else active_reason,
        ),
        _stream_entry(
            "api_thumbnail",
            "API Thumbnail",
            data.get("thumbnail_url"),
            None,
            SNAPSHOT_TYPE == "api",
            "disabled" if SNAPSHOT_TYPE != "api" else "",
        ),
    ]
    return streams


def format_stream(name_uri: str) -> dict:
    """
    Format stream with hostname.

    Parameters:
    - name_uri (str): camera name.

    Returns:
    - dict: Can be merged with camera info.
    """
    hostname = env_bool("DOMAIN", urlparse(request.root_url).hostname or "localhost")
    img = f"{name_uri}.{IMG_TYPE}"
    img_time = None
    img_candidates = [img]
    if name_uri.endswith("-sub"):
        img_candidates.append(f"{name_uri.removesuffix('-sub')}.{IMG_TYPE}")
    else:
        img_candidates.append(f"{name_uri}-sub.{IMG_TYPE}")
    for img_candidate in img_candidates:
        img_path = IMG_PATH + img_candidate
        if not preview_file_is_image(img_path):
            continue
        try:
            candidate_time = int(os.path.getmtime(img_path) * 1000)
        except FileNotFoundError:
            continue
        if img_time is None or candidate_time > img_time:
            img = img_candidate
            img_time = candidate_time

    webrtc_url = (WEBRTC_URL or f"http://{hostname}:8889") + f"/{name_uri}/"
    preview_kind = "api" if SNAPSHOT_TYPE == "api" else "rtsp"
    preview_url = f"img/{img}"
    data = {
        "uri": name_uri,
        "hls_url": (HLS_URL or f"http://{hostname}:8888") + f"/{name_uri}/",
        "webrtc_url": webrtc_url if BRIDGE_IP else None,
        "rtmp_url": (RTMP_URL or f"rtmp://{hostname}:1935") + f"/{name_uri}",
        "rtsp_url": (RTSP_URL or f"rtsp://{hostname}:8554") + f"/{name_uri}",
        "img_url": f"img/{img}" if img_time else None,
        "snapshot_url": f"snapshot/{img}",
        "thumbnail_url": f"thumb/{img}",
        "img_time": img_time,
        "preview_url": preview_url,
        "preview_kind": preview_kind,
        "preview_refresh_mode": preview_refresh_route(SNAPSHOT_TYPE),
    }
    if LLHLS:
        data["hls_url"] = data["hls_url"].replace("http:", "https:")
    return data


def _normalize_camera_urls(camera: dict, stream_data: dict) -> dict:
    hostname = env_bool("DOMAIN", urlparse(request.root_url).hostname or "localhost")
    normalized = {}
    for key in ("hls_url", "webrtc_url", "rtsp_url", "rtmp_url"):
        if key not in camera:
            continue
        value = camera.get(key)
        normalized[key] = _replace_url_host(value, hostname) if value else value
    if camera.get("native_selected") and camera.get("native_rtsp_url"):
        normalized["rtsp_url"] = _replace_url_host(camera.get("native_rtsp_url"), hostname)
    return normalized


def format_streams(cams: dict) -> dict[str, dict]:
    """
    Format info for multiple streams with hostname.

    Parameters:
    - cams (dict): get_all_cam_info from StreamManager.

    Returns:
    - dict: cam info with hostname.
    """
    formatted = {}
    for uri, cam in cams.items():
        stream_data = format_stream(uri)
        formatted[uri] = cam | stream_data
        formatted[uri] |= _normalize_camera_urls(cam, stream_data)
        formatted[uri]["streams"] = build_stream_entries(formatted[uri], stream_data)
    return formatted


def all_cams(streams: StreamManager, total: int, cameras: Optional[dict] = None) -> dict:
    formatted = format_streams(cameras if cameras is not None else streams.get_all_cam_info())
    return {
        "total": total,
        "available": len(formatted),
        "enabled": sum(1 for camera in formatted.values() if camera.get("enabled")),
        "cameras": formatted,
    }


def boa_snapshot(stream: Stream) -> Optional[dict]:
    """Take photo."""
    stream.send_cmd("take_photo")
    if boa_info := stream.get_info("boa_info"):
        return boa_info.get("last_photo")

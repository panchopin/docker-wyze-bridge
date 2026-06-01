#!/usr/bin/env python3

import pathlib
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(
    0, str(pathlib.Path(__file__).resolve().parent.parent / ".ha_live_addon" / "app")
)

from wyzecam.api_models import WyzeCamera
import wyzebridge.wyze_api as wyze_api_module
from wyzebridge.wyze_api import WHEP_PROXY_PORT, WyzeApi


def make_camera(model: str = "HL_CAM4", nickname: str = "North Yard") -> WyzeCamera:
    return WyzeCamera(
        p2p_id="P2P-ID",
        p2p_type=1,
        ip="192.168.1.176",
        enr="ENR-VALUE",
        mac="001122334455",
        product_model=model,
        nickname=nickname,
        timezone_name="America/Edmonton",
        firmware_ver="4.52.9.5332",
        dtls=1,
        parent_dtls=0,
        parent_enr=None,
        parent_mac=None,
        thumbnail=None,
    )


class FakeParams:
    def __init__(self):
        self.signaling_url = "wss://signal.example/ws%3Fcamera%3Dnorth-yard"
        self.auth_token = "token-abc"
        self.ice_servers = [
            {"url": "stun:stun.example:3478", "username": "user", "credential": "pass"}
        ]

    def model_dump(self):
        return {
            "signaling_url": self.signaling_url,
            "auth_token": self.auth_token,
            "ice_servers": self.ice_servers,
        }


class FakeStream:
    def __init__(self):
        self.params = FakeParams()


class FakeResponse:
    def raise_for_status(self):
        return None


class TestKVSSubstreamProxyConfig(unittest.TestCase):
    def setUp(self):
        self.api = WyzeApi()
        self.api.auth = SimpleNamespace(phone_id="phone-123", access_token="token-abc")

    def test_substream_proxy_config_uses_base_camera_lookup(self):
        camera = make_camera()

        with (
            patch.object(WyzeApi, "get_camera", return_value=camera) as get_camera,
            patch.object(WyzeApi, "_maybe_wake_kvs_camera"),
            patch.object(wyze_api_module, "get_camera_stream", return_value=FakeStream()),
        ):
            config = self.api.get_kvs_proxy_config("north-yard-sub")

        get_camera.assert_called_with("north-yard", True)
        self.assertEqual(config["camera_name"], "north-yard")
        self.assertEqual(config["stream_id"], "north-yard-sub")
        self.assertEqual(config["quality"], "sd30")
        self.assertTrue(config["substream"])
        self.assertEqual(config["phone_id"], "phone-123")
        self.assertEqual(config["signaling_url"], "wss://signal.example/ws?camera=north-yard")

    def test_hl_bc_main_path_proxy_config_uses_sd_quality(self):
        camera = make_camera("HL_BC", "South Yard")

        with (
            patch.object(WyzeApi, "get_camera", return_value=camera) as get_camera,
            patch.object(WyzeApi, "_maybe_wake_kvs_camera"),
            patch.object(wyze_api_module, "get_camera_stream", return_value=FakeStream()) as get_camera_stream,
            patch.object(wyze_api_module, "get_cam_webrtc") as get_cam_webrtc,
        ):
            config = self.api.get_kvs_proxy_config("south-yard")

        get_camera.assert_called_with("south-yard", True)
        get_camera_stream.assert_called_once_with(self.api.auth, camera)
        get_cam_webrtc.assert_not_called()
        self.assertEqual(config["camera_name"], "south-yard")
        self.assertEqual(config["stream_id"], "south-yard")
        self.assertEqual(config["quality"], "sd30")
        self.assertFalse(config["substream"])
        self.assertEqual(config["phone_id"], "phone-123")

    def test_hl_bc_main_path_wakes_camera_before_proxy_config(self):
        camera = make_camera("HL_BC", "South Yard")

        with (
            patch.object(WyzeApi, "get_camera", return_value=camera),
            patch.object(wyze_api_module, "wakeup_kvs_camera") as wakeup,
            patch.object(wyze_api_module, "get_camera_stream", return_value=FakeStream()),
        ):
            config = self.api.get_kvs_proxy_config("south-yard")

        self.assertEqual(config["stream_id"], "south-yard")
        wakeup.assert_called_once_with(self.api.auth, camera)

    def test_setup_mtx_proxy_posts_substream_uri(self):
        kvs_config = {"signaling_url": "wss://signal.example/ws", "stream_id": "north-yard-sub"}

        with (
            patch.object(WyzeApi, "get_kvs_proxy_config", return_value=kvs_config) as get_kvs_proxy_config,
            patch.object(wyze_api_module.requests, "post", return_value=FakeResponse()) as post,
            patch("wyzebridge.wyze_api.requests.get", return_value=FakeResponse()),
        ):
            result = self.api.setup_mtx_proxy("north-yard-sub")

        self.assertTrue(result)
        get_kvs_proxy_config.assert_called_with("north-yard-sub")
        post.assert_called_with(
            f"http://127.0.0.1:{WHEP_PROXY_PORT}/websocket/north-yard-sub",
            json=kvs_config,
            headers={"Content-Type": "application/json"},
            timeout=10,
        )


if __name__ == "__main__":
    unittest.main()

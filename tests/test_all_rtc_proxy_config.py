#!/usr/bin/env python3

import pathlib
import sys
import unittest
from unittest.mock import patch

sys.path.insert(
    0, str(pathlib.Path(__file__).resolve().parent.parent / ".ha_live_addon" / "app")
)

from wyzecam.api_models import WyzeCamera
import wyzebridge.wyze_api as wyze_api_module
from wyzebridge.wyze_api import WyzeApi


def make_camera(model: str, nickname: str) -> WyzeCamera:
    return WyzeCamera(
        p2p_id="P2P-ID",
        p2p_type=1,
        ip="192.168.1.100",
        enr="ENR-VALUE",
        mac="001122334455",
        product_model=model,
        nickname=nickname,
        timezone_name="America/Edmonton",
        firmware_ver="1.0.0.0",
        dtls=1,
        parent_dtls=0,
        parent_enr=None,
        parent_mac=None,
        thumbnail=None,
    )


class TestAllRTCProxyConfig(unittest.TestCase):
    def setUp(self):
        self.api = WyzeApi()
        self.api.auth = type("Auth", (), {"phone_id": "phone-123"})()

    def test_standard_webrtc_camera_maps_to_proxy_config(self):
        cam = make_camera("WYZE_CAKP2JFUS", "Garage")
        signal = {
            "signalingUrl": "wss://signal.example/ws",
            "ClientId": "phone-123",
            "signalToken": "token-abc",
            "servers": [
                {"urls": ["stun:stun.example:3478"], "username": "u", "credential": "c"}
            ],
        }

        with (
            patch.object(WyzeApi, "get_camera", return_value=cam),
            patch.object(WyzeApi, "_maybe_wake_kvs_camera"),
            patch.object(wyze_api_module, "get_cam_webrtc", return_value=signal),
        ):
            config = self.api.get_kvs_proxy_config(cam.name_uri)

        self.assertEqual(config["signaling_url"], "wss://signal.example/ws")
        self.assertEqual(config["auth_token"], "token-abc")
        self.assertEqual(config["phone_id"], "phone-123")
        self.assertEqual(config["ice_servers"][0]["url"], "stun:stun.example:3478")

    def test_non_webrtc_camera_does_not_use_proxy(self):
        cam = make_camera("WYZEC1", "Old Cam")
        with patch.object(WyzeApi, "get_camera", return_value=cam):
            config = self.api.get_kvs_proxy_config(cam.name_uri)

        self.assertIsNone(config)


if __name__ == "__main__":
    unittest.main()

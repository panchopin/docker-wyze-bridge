#!/usr/bin/env python3

import os
import pathlib
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(
    0, str(pathlib.Path(__file__).resolve().parent.parent / ".ha_live_addon" / "app")
)

import wyzecam.api as wyzecam_api_module
from wyzecam.api_models import WyzeCamera
import wyzebridge.wyze_api as wyze_api_module
from wyzebridge.wyze_api import WyzeApi


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


class DummyResponse:
    pass


class FakeProperty:
    def model_dump(self, by_alias: bool = False):
        return {"property": {"bitrate": 180, "res": 1}}


class FakeParams:
    def __init__(self):
        self.signaling_url = "wss://signal.example/ws%3Fcamera%3Dnorth-yard"
        self.auth_token = "token-abc"
        self.ice_servers = [
            {
                "url": "turn:turn.example:3478?transport=udp",
                "username": "trace-user",
                "credential": "trace-secret",
            }
        ]

    def model_dump(self):
        return {
            "signaling_url": self.signaling_url,
            "auth_token": self.auth_token,
            "ice_servers": self.ice_servers,
        }


class FakeStream:
    def __init__(self):
        self.property = FakeProperty()
        self.params = FakeParams()


class TestKVSTraceLogging(unittest.TestCase):
    def test_get_camera_stream_logs_redacted_raw_stream_trace(self):
        camera = make_camera()
        auth = SimpleNamespace(access_token="access-token")
        stream_info = {
            "property": {"property": {"bitrate": 180, "res": 1}},
            "device_id": camera.mac,
            "provider": "webrtc",
            "params": {
                "signaling_url": "wss://signal.example/ws?camera=north-yard",
                "auth_token": "token-abc",
                "ice_servers": [
                    {
                        "url": "turn:turn.example:3478?transport=udp",
                        "username": "trace-user",
                        "credential": "trace-secret",
                    }
                ],
            },
        }

        with (
            patch.dict(os.environ, {"KVS_TRACE_STREAM": "north-yard"}, clear=False),
            patch.object(wyzecam_api_module, "sign_payload", return_value={}),
            patch.object(wyzecam_api_module, "post", return_value=DummyResponse()),
            patch.object(wyzecam_api_module, "validate_resp", return_value=[stream_info]),
            patch.object(wyzecam_api_module.logger, "info") as log_info,
        ):
            stream = wyzecam_api_module.get_camera_stream(auth, camera)

        self.assertEqual(stream.device_id, camera.mac)
        messages = [call.args[0] for call in log_info.call_args_list]
        trace = next(message for message in messages if "[KVS_TRACE]" in message)
        self.assertIn('"stage": "raw_stream_info"', trace)
        self.assertIn('"camera": "north-yard"', trace)
        self.assertIn('"<redacted>"', trace)
        self.assertNotIn("token-abc", trace)
        self.assertNotIn("trace-user", trace)
        self.assertNotIn("trace-secret", trace)

    def test_get_kvs_proxy_config_logs_redacted_derived_trace(self):
        camera = make_camera()
        api = WyzeApi()
        api.auth = SimpleNamespace(phone_id="phone-123", access_token="token-abc")

        with (
            patch.dict(os.environ, {"KVS_TRACE_STREAM": "north-yard"}, clear=False),
            patch.object(WyzeApi, "get_camera", return_value=camera),
            patch.object(WyzeApi, "_maybe_wake_kvs_camera"),
            patch.object(wyze_api_module, "get_camera_stream", return_value=FakeStream()),
            patch.object(wyze_api_module.logger, "info") as log_info,
        ):
            config = api.get_kvs_proxy_config("north-yard-sub")

        self.assertEqual(config["camera_name"], "north-yard")
        self.assertEqual(config["stream_id"], "north-yard-sub")
        self.assertEqual(config["quality"], "sd30")
        self.assertTrue(config["substream"])
        messages = [call.args[0] for call in log_info.call_args_list]
        raw_trace = next(message for message in messages if '"stage": "raw_proxy_params"' in message)
        derived_trace = next(
            message for message in messages if '"stage": "derived_kvs_config"' in message
        )
        self.assertIn('"requested_quality": "sd30"', raw_trace)
        self.assertIn('"camera_name": "north-yard"', derived_trace)
        self.assertIn('"stream_id": "north-yard-sub"', derived_trace)
        self.assertIn('"<redacted>"', derived_trace)
        self.assertNotIn("phone-123", derived_trace)
        self.assertNotIn("token-abc", derived_trace)


if __name__ == "__main__":
    unittest.main()

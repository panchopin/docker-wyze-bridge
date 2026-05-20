#!/usr/bin/env python3

import importlib
import pathlib
import sys
import types
import unittest
from types import SimpleNamespace
from unittest.mock import patch

APP_DIR = pathlib.Path(__file__).resolve().parent.parent / "app"
APP_DIR_STR = str(APP_DIR)
while APP_DIR_STR in sys.path:
    sys.path.remove(APP_DIR_STR)
sys.path.insert(0, APP_DIR_STR)

sys.modules.setdefault("xxtea", types.ModuleType("xxtea"))

fake_wyzecam_iotc = types.ModuleType("wyzecam.iotc")
fake_wyzecam_iotc.WyzeIOTC = object
fake_wyzecam_iotc.WyzeIOTCSession = object
sys.modules.setdefault("wyzecam.iotc", fake_wyzecam_iotc)


class FakeApi:
    def __init__(self, bridge_can_substream=True, product_model="HL_CAM4"):
        self.auth = True
        self.total_cams = 1
        self._bridge_can_substream = bridge_can_substream
        self._product_model = product_model

    def get_camera(self, cam_name, existing=False):
        if cam_name != "north-yard":
            return None
        return SimpleNamespace(
            name_uri="north-yard",
            bridge_can_substream=self._bridge_can_substream,
            product_model=self._product_model,
        )

    def filtered_cams(self):
        camera = self.get_camera("north-yard")
        return [camera] if camera else []


class FakeStreams:
    def get_info(self, cam_name):
        if cam_name == "north-yard":
            return {"name_uri": "north-yard"}
        return {}


class FakeBridge:
    stream_config = {
        "mode": "main",
        "feeds": {
            "hd": {
                "enabled": True,
                "supported": True,
                "kbps": 180,
                "resolution": "2560x1440",
                "path": "main",
                "reason": "",
            },
            "sd": {
                "enabled": False,
                "supported": True,
                "kbps": 30,
                "resolution": "640x360",
                "path": "sub",
                "reason": "",
            },
        },
    }
    bridge_can_substream = True
    product_model = "HL_CAM4"
    last_payload = None
    apply_error = None

    def __init__(self):
        self.api = FakeApi(self.bridge_can_substream, self.product_model)
        self.streams = FakeStreams()

    def start(self):
        return None

    def camera_stream_mode(self, camera):
        return self.stream_config["mode"]

    def camera_substream_enabled(self, camera):
        return self.stream_config["feeds"]["sd"]["enabled"] and camera.bridge_can_substream

    def camera_stream_config(self, camera):
        return self.stream_config

    def camera_catalog(self):
        if self.stream_config["feeds"]["hd"]["enabled"]:
            return {
                "north-yard": {
                    "name_uri": "north-yard",
                    "camera_uri": "north-yard",
                    "nickname": "North Yard",
                    "enabled": True,
                    "connected": False,
                    "camera_info": None,
                    "on_demand": False,
                    "substream": False,
                    "audio": True,
                    "record": False,
                    "webrtc": True,
                    "rtsp_fw_enabled": False,
                    "boa_url": None,
                    "motion": False,
                    "motion_ts": 0,
                    "status": "stopped",
                    "source": "kvs",
                    "start_time": 0,
                    "req_frame_size": 0,
                    "req_bitrate": 0,
                    "actual_resolution": self.stream_config["feeds"]["hd"]["resolution"],
                    "bridge_can_substream": self.bridge_can_substream,
                    "camera_can_substream": self.bridge_can_substream,
                    "model_name": "Test Cam",
                    "is_2k": self.product_model == "HL_CAM4",
                    "rtsp_fw": False,
                    "is_battery": False,
                    "native_selected": False,
                    "native_alias": "north-yard",
                    "native_rtsp_url": "rtsp://127.0.0.1:19554/north-yard",
                }
            }
        return {
            "north-yard": {
                "name_uri": "north-yard",
                "camera_uri": "north-yard",
                "nickname": "North Yard",
                "enabled": True,
                "connected": True,
                "camera_info": None,
                "on_demand": False,
                "substream": False,
                "audio": True,
                "record": False,
                "webrtc": False,
                "rtsp_fw_enabled": False,
                "boa_url": None,
                "motion": False,
                "motion_ts": 0,
                "status": "connected",
                "source": "go2rtc",
                "start_time": 0,
                "req_frame_size": 0,
                "req_bitrate": 0,
                "actual_resolution": self.stream_config["feeds"]["sd"]["resolution"],
                "bridge_can_substream": self.bridge_can_substream,
                "camera_can_substream": self.bridge_can_substream,
                "model_name": "Test Cam",
                "is_2k": self.product_model == "HL_CAM4",
                "rtsp_fw": False,
                "is_battery": False,
                "native_selected": True,
                "native_alias": "north-yard-sd",
                "native_rtsp_url": "rtsp://127.0.0.1:19554/north-yard-sd",
                "rtsp_url": "rtsp://127.0.0.1:19554/north-yard-sd",
                "hls_url": None,
                "webrtc_url": None,
                "rtmp_url": None,
            }
        }

    def camera_info(self, cam_name):
        return self.camera_catalog().get(cam_name, {})

    def apply_camera_stream_config(self, camera, payload):
        type(self).last_payload = payload
        if self.apply_error:
            raise ValueError(self.apply_error)
        return self.stream_config

    def refresh_cams(self):
        return None


fake_wyze_bridge = types.ModuleType("wyze_bridge")
fake_wyze_bridge.WyzeBridge = FakeBridge
sys.modules["wyze_bridge"] = fake_wyze_bridge

import frontend


class TestFrontendStreamMode(unittest.TestCase):
    def create_client(self):
        while APP_DIR_STR in sys.path:
            sys.path.remove(APP_DIR_STR)
        sys.path.insert(0, APP_DIR_STR)
        sys.modules["wyze_bridge"] = fake_wyze_bridge
        importlib.reload(frontend)
        frontend.WbAuth.enabled = False
        app = frontend.create_app()
        app.testing = True
        return app.test_client()

    def test_stream_config_reports_current_feed_state(self):
        FakeBridge.stream_config = {
            "mode": "both",
            "feeds": {
                "hd": {
                    "enabled": True,
                    "supported": True,
                    "kbps": 180,
                    "resolution": "2560x1440",
                    "path": "main",
                    "reason": "",
                },
                "sd": {
                    "enabled": True,
                    "supported": True,
                    "kbps": 30,
                    "resolution": "640x360",
                    "path": "sub",
                    "reason": "",
                },
            },
        }
        FakeBridge.bridge_can_substream = True
        FakeBridge.product_model = "HL_CAM4"
        client = self.create_client()

        response = client.get("/api/north-yard/stream-config")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["mode"], "both")
        self.assertTrue(response.get_json()["feeds"]["hd"]["supported"])
        self.assertTrue(response.get_json()["feeds"]["sd"]["supported"])
        self.assertEqual(response.get_json()["feeds"]["sd"]["resolution"], "640x360")

    def test_stream_config_reports_sd_only_bulb_cam_state(self):
        FakeBridge.stream_config = {
            "mode": "sub",
            "feeds": {
                "hd": {
                    "enabled": False,
                    "supported": False,
                    "kbps": 120,
                    "resolution": None,
                    "path": "main",
                    "reason": "HD stream is not available for this camera",
                },
                "sd": {
                    "enabled": True,
                    "supported": True,
                    "kbps": 30,
                    "resolution": "640x360",
                    "path": "main",
                    "reason": "",
                },
            },
        }
        FakeBridge.bridge_can_substream = True
        FakeBridge.product_model = "HL_BC"
        client = self.create_client()

        response = client.get("/api/north-yard/stream-config")

        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.get_json()["feeds"]["hd"]["supported"])
        self.assertTrue(response.get_json()["feeds"]["sd"]["supported"])
        self.assertEqual(response.get_json()["feeds"]["sd"]["path"], "main")

    def test_stream_config_reports_native_paths_when_selected(self):
        FakeBridge.stream_config = {
            "mode": "sub",
            "feeds": {
                "hd": {
                    "enabled": False,
                    "supported": True,
                    "kbps": 180,
                    "resolution": "1296x1728",
                    "path": "main",
                    "reason": "",
                },
                "sd": {
                    "enabled": True,
                    "supported": True,
                    "kbps": 30,
                    "resolution": "640x360",
                    "path": "native",
                    "reason": "",
                },
            },
        }
        FakeBridge.bridge_can_substream = True
        FakeBridge.product_model = "HL_CAM4"
        client = self.create_client()

        response = client.get("/api/north-yard/stream-config")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["feeds"]["sd"]["path"], "native")

    def test_stream_config_rejects_unsupported_feed_selection(self):
        FakeBridge.apply_error = "HD stream is not available for this camera"
        FakeBridge.bridge_can_substream = True
        FakeBridge.product_model = "HL_BC"
        client = self.create_client()

        response = client.post(
            "/api/north-yard/stream-config",
            json={"hd_enabled": True, "sd_enabled": True, "hd_kbps": 120, "sd_kbps": 30},
        )

        self.assertEqual(response.status_code, 409)
        self.assertIn("not available", response.get_json()["response"])

    def test_stream_config_accepts_granular_updates(self):
        FakeBridge.apply_error = None
        FakeBridge.last_payload = None
        FakeBridge.stream_config = {
            "mode": "both",
            "feeds": {
                "hd": {
                    "enabled": True,
                    "supported": True,
                    "kbps": 150,
                    "resolution": "1920x1080",
                    "path": "main",
                    "reason": "",
                },
                "sd": {
                    "enabled": True,
                    "supported": True,
                    "kbps": 60,
                    "resolution": "640x360",
                    "path": "sub",
                    "reason": "",
                },
            },
        }
        FakeBridge.bridge_can_substream = True
        FakeBridge.product_model = "WYZE_CAKP2JFUS"
        client = self.create_client()

        response = client.post(
            "/api/north-yard/stream-config",
            json={"hd_enabled": True, "sd_enabled": True, "hd_kbps": 150, "sd_kbps": 60},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(FakeBridge.last_payload["hd_kbps"], 150)
        self.assertEqual(FakeBridge.last_payload["sd_kbps"], 60)
        self.assertTrue(response.get_json()["feeds"]["hd"]["enabled"])

    def test_api_lists_native_only_camera_in_catalog(self):
        FakeBridge.stream_config = {
            "mode": "sub",
            "feeds": {
                "hd": {
                    "enabled": False,
                    "supported": True,
                    "kbps": 180,
                    "resolution": "1296x1728",
                    "path": "main",
                    "reason": "",
                },
                "sd": {
                    "enabled": True,
                    "supported": True,
                    "kbps": 30,
                    "resolution": "640x360",
                    "path": "native",
                    "reason": "",
                },
            },
        }
        client = self.create_client()

        response = client.get("/api")

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload["available"], 1)
        self.assertEqual(payload["enabled"], 1)
        self.assertIn("north-yard", payload["cameras"])
        self.assertEqual(
            payload["cameras"]["north-yard"]["rtsp_url"],
            "rtsp://localhost:19554/north-yard-sd",
        )

    def test_api_returns_loading_when_catalog_has_not_populated_yet(self):
        client = self.create_client()

        with patch.object(FakeBridge, "camera_catalog", return_value={}):
            response = client.get("/api")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json(), {"status": "loading"})

    def test_api_ready_returns_loading_until_native_aliases_are_seeded(self):
        client = self.create_client()
        catalog = {
            "north-yard": {
                "native_selected": True,
                "native_alias": "north-yard",
                "source": "go2rtc",
            }
        }

        with (
            patch.object(FakeBridge, "camera_catalog", return_value=catalog),
            patch(
                "frontend.go2rtc_probe",
                return_value={"api": {"reachable": True}, "aliases": []},
            ),
        ):
            response = client.get("/api/ready")

        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.get_json(), {"status": "loading"})

    def test_api_ready_returns_loading_when_go2rtc_probe_errors(self):
        client = self.create_client()
        catalog = {
            "north-yard": {
                "native_selected": True,
                "native_alias": "north-yard",
                "source": "go2rtc",
            }
        }

        with (
            patch.object(FakeBridge, "camera_catalog", return_value=catalog),
            patch("frontend.go2rtc_probe", side_effect=RuntimeError("probe failed")),
        ):
            response = client.get("/api/ready")

        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.get_json(), {"status": "loading"})

    def test_api_ready_returns_ready_when_catalog_and_aliases_are_present(self):
        client = self.create_client()
        catalog = {
            "north-yard": {
                "native_selected": True,
                "native_alias": "north-yard",
                "source": "go2rtc",
            }
        }

        with (
            patch.object(FakeBridge, "camera_catalog", return_value=catalog),
            patch(
                "frontend.go2rtc_probe",
                return_value={
                    "api": {"reachable": True},
                    "aliases": ["north-yard", "north-yard-sd"],
                },
            ),
        ):
            response = client.get("/api/ready")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json(), {"status": "ready"})

    def test_api_ready_ignores_native_alias_when_sd_feed_fell_back_to_bridge(self):
        client = self.create_client()
        catalog = {
            "north-yard": {
                "native_selected": True,
                "native_alias": "north-yard",
                "source": "kvs",
            }
        }

        with (
            patch.object(FakeBridge, "camera_catalog", return_value=catalog),
            patch(
                "frontend.go2rtc_probe",
                return_value={"api": {"reachable": True}, "aliases": []},
            ),
        ):
            response = client.get("/api/ready")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json(), {"status": "ready"})

    def test_api_ready_never_falls_through_to_camera_lookup(self):
        client = self.create_client()

        response = client.get("/api/ready")

        self.assertNotIn("Could not find camera [ready]", response.get_data(as_text=True))
        self.assertIn(response.get_json()["status"], {"loading", "ready"})

    def test_native_only_camera_uses_image_preview_when_video_enabled(self):
        FakeBridge.stream_config = {
            "mode": "sub",
            "feeds": {
                "hd": {
                    "enabled": False,
                    "supported": True,
                    "kbps": 180,
                    "resolution": "1296x1728",
                    "path": "main",
                    "reason": "",
                },
                "sd": {
                    "enabled": True,
                    "supported": True,
                    "kbps": 30,
                    "resolution": "640x360",
                    "path": "native",
                    "reason": "",
                },
            },
        }
        client = self.create_client()

        response = client.get("/?video=1")
        html = response.get_data(as_text=True)

        self.assertEqual(response.status_code, 200)
        self.assertIn('src="img/north-yard.jpg"', html)
        self.assertNotIn('data-src="Nonestream.m3u8"', html)

#!/usr/bin/env python3

import pathlib
import sys
import types
import unittest
from types import SimpleNamespace
from unittest.mock import patch

requests_stub = types.ModuleType("requests")
requests_exceptions = types.ModuleType("requests.exceptions")
requests_stub.RequestException = Exception
requests_stub.ConnectionError = Exception
requests_stub.HTTPError = Exception
requests_stub.PreparedRequest = object
requests_stub.Response = object
requests_stub.get = lambda *args, **kwargs: None
requests_stub.post = lambda *args, **kwargs: None
requests_stub.put = lambda *args, **kwargs: None
requests_exceptions.ConnectionError = Exception
requests_exceptions.HTTPError = Exception
requests_exceptions.RequestException = Exception
requests_stub.exceptions = requests_exceptions
sys.modules.setdefault("requests", requests_stub)
sys.modules.setdefault("requests.exceptions", requests_exceptions)

sys.modules.setdefault(
    "dotenv",
    SimpleNamespace(load_dotenv=lambda *args, **kwargs: False),
)
sys.modules.setdefault("xxtea", types.ModuleType("xxtea"))

fake_wyzecam_iotc = types.ModuleType("wyzecam.iotc")
fake_wyzecam_iotc.WyzeIOTC = object
fake_wyzecam_iotc.WyzeIOTCSession = object
sys.modules.setdefault("wyzecam.iotc", fake_wyzecam_iotc)

sys.path.insert(
    0, str(pathlib.Path(__file__).resolve().parent.parent / ".ha_live_addon" / "app")
)

if not hasattr(sys.modules.get("wyzebridge.wyze_stream"), "StreamStatus"):
    for module_name in list(sys.modules):
        if module_name == "wyzebridge" or module_name.startswith("wyzebridge."):
            del sys.modules[module_name]

from wyzebridge.wyze_stream import StreamStatus, WyzeStream

if not hasattr(sys.modules["wyzebridge.wyze_stream"], "publish_discovery"):
    sys.modules["wyzebridge.wyze_stream"].publish_discovery = lambda *args, **kwargs: None


class DummyApi:
    pass


def make_camera():
    return SimpleNamespace(
        name_uri="garage",
        nickname="Garage",
        product_model="WYZE_CAKP2JFUS",
        model_name="Wyze Cam v3",
        ip="192.168.1.10",
        is_gwell=False,
        is_battery=False,
        is_floodlight=False,
        is_2k=False,
        is_kvs=True,
        can_substream=False,
        bridge_can_substream=False,
        rtsp_fw=False,
        camera_info=None,
        webrtc_support=True,
        mac="001122334455",
        p2p_id="p2p-id",
        dtls=1,
        parent_dtls=0,
        enr="enr",
        model_dump=lambda exclude=None: {"product_model": "WYZE_CAKP2JFUS"},
    )


class TestKVSStreamGetInfo(unittest.TestCase):
    def test_connected_kvs_stream_skips_tutk_caminfo_when_control_queue_missing(self):
        user = SimpleNamespace()
        camera = make_camera()

        with patch("wyzebridge.wyze_stream.publish_discovery", create=True):
            stream = WyzeStream(
                user,
                DummyApi(),
                camera,
                SimpleNamespace(
                    quality="hd180",
                    audio=True,
                    record=False,
                    reconnect=True,
                    substream=False,
                    frame_size=0,
                    bitrate=180,
                    update_quality=lambda hq: None,
                ),
            )

        stream.state = StreamStatus.CONNECTED

        info = stream.get_info()

        self.assertTrue(info["connected"])
        self.assertEqual(info["product_model"], "WYZE_CAKP2JFUS")
        self.assertFalse(info["native_supported"])
        self.assertFalse(info["native_selected"])

    @patch("wyzebridge.go2rtc.requests.get")
    def test_hl_cam4_reports_native_selection_when_go2rtc_api_is_reachable(self, mock_get):
        user = SimpleNamespace()
        camera = make_camera()
        camera.product_model = "HL_CAM4"
        camera.model_name = "Wyze Cam v4"
        response = SimpleNamespace(status_code=200, raise_for_status=lambda: None)
        mock_get.return_value = response

        with patch("wyzebridge.wyze_stream.publish_discovery", create=True):
            stream = WyzeStream(
                user,
                DummyApi(),
                camera,
                SimpleNamespace(
                    quality="hd180",
                    audio=True,
                    record=False,
                    reconnect=True,
                    substream=False,
                    frame_size=0,
                    bitrate=180,
                    update_quality=lambda hq: None,
                ),
            )

        info = stream.get_info()

        self.assertTrue(info["native_supported"])
        self.assertTrue(info["native_selected"])
        self.assertEqual(info["native_alias"], "garage")
        self.assertEqual(info["snapshot_source"], "go2rtc")
        self.assertTrue(info["talkback_supported"])
        self.assertEqual(info["talkback_alias"], "garage")
        self.assertEqual(info["talkback_source"], "go2rtc")

    @patch("wyzebridge.go2rtc.requests.get")
    def test_sd_only_bridge_feed_does_not_report_native_snapshot_source(self, mock_get):
        user = SimpleNamespace()
        camera = make_camera()
        camera.product_model = "HL_CAM4"
        camera.model_name = "Wyze Cam v4"
        response = SimpleNamespace(status_code=200, raise_for_status=lambda: None)
        mock_get.return_value = response

        with (
            patch("wyzebridge.wyze_stream.publish_discovery", create=True),
            patch.dict("os.environ", {"SD_ONLY": "true"}, clear=False),
        ):
            stream = WyzeStream(
                user,
                DummyApi(),
                camera,
                SimpleNamespace(
                    quality="sd30",
                    audio=True,
                    record=False,
                    reconnect=True,
                    substream=False,
                    frame_size=1,
                    bitrate=30,
                    update_quality=lambda hq: None,
                ),
            )
            info = stream.get_info()

        self.assertFalse(info["native_selected"])
        self.assertEqual(info["snapshot_source"], "rtsp")
        self.assertFalse(info["talkback_supported"])

    @patch("wyzebridge.go2rtc.requests.get")
    def test_hl_bc_reports_talkback_as_unavailable_when_bridge_first(self, mock_get):
        user = SimpleNamespace()
        camera = make_camera()
        camera.product_model = "HL_BC"
        camera.model_name = "Wyze Bulb Cam"
        response = SimpleNamespace(status_code=200, raise_for_status=lambda: None)
        mock_get.return_value = response

        with patch("wyzebridge.wyze_stream.publish_discovery", create=True):
            stream = WyzeStream(
                user,
                DummyApi(),
                camera,
                SimpleNamespace(
                    quality="hd180",
                    audio=True,
                    record=False,
                    reconnect=True,
                    substream=False,
                    frame_size=0,
                    bitrate=180,
                    update_quality=lambda hq: None,
                ),
            )

        info = stream.get_info()

        self.assertTrue(info["native_supported"])
        self.assertFalse(info["native_selected"])
        self.assertFalse(info["talkback_supported"])
        self.assertEqual(info["talkback_alias"], "garage")
        self.assertIn("native-selected cameras", info["talkback_reason"])

    @patch("wyzebridge.go2rtc.requests.get")
    def test_hl_cam3p_selects_only_native_sd_feed(self, mock_get):
        user = SimpleNamespace()
        camera = make_camera()
        camera.product_model = "HL_CAM3P"
        camera.model_name = "Wyze Cam V3 Pro"
        response = SimpleNamespace(status_code=200, raise_for_status=lambda: None)
        mock_get.return_value = response

        with patch("wyzebridge.wyze_stream.publish_discovery", create=True):
            main_stream = WyzeStream(
                user,
                DummyApi(),
                camera,
                SimpleNamespace(
                    quality="hd180",
                    audio=True,
                    record=False,
                    reconnect=True,
                    substream=False,
                    frame_size=3,
                    bitrate=180,
                    update_quality=lambda hq: None,
                ),
            )
            sub_stream = WyzeStream(
                user,
                DummyApi(),
                camera,
                SimpleNamespace(
                    quality="sd30",
                    audio=True,
                    record=False,
                    reconnect=True,
                    substream=True,
                    frame_size=1,
                    bitrate=30,
                    update_quality=lambda hq: None,
                ),
            )

        main_info = main_stream.get_info()
        sub_info = sub_stream.get_info()

        self.assertTrue(main_info["native_supported"])
        self.assertFalse(main_info["native_selected"])
        self.assertEqual(main_info["snapshot_source"], "rtsp")
        self.assertFalse(main_info["talkback_supported"])
        self.assertTrue(sub_info["native_supported"])
        self.assertTrue(sub_info["native_selected"])
        self.assertEqual(sub_info["native_alias"], "garage-sd")
        self.assertEqual(sub_info["snapshot_source"], "go2rtc")
        self.assertFalse(sub_info["talkback_supported"])

    @patch("wyzebridge.go2rtc.requests.get")
    def test_hl_bc_reports_sd_resolution_for_main_feed(self, mock_get):
        user = SimpleNamespace()
        camera = make_camera()
        camera.product_model = "HL_BC"
        camera.model_name = "Wyze Bulb Cam"
        response = SimpleNamespace(status_code=200, raise_for_status=lambda: None)
        mock_get.return_value = response

        with patch("wyzebridge.wyze_stream.publish_discovery", create=True):
            stream = WyzeStream(
                user,
                DummyApi(),
                camera,
                SimpleNamespace(
                    quality="sd30",
                    audio=True,
                    record=False,
                    reconnect=True,
                    substream=False,
                    frame_size=1,
                    bitrate=30,
                    update_quality=lambda hq: None,
                ),
            )

        info = stream.get_info()

        self.assertEqual(info["actual_resolution"], "640x360")


if __name__ == "__main__":
    unittest.main()

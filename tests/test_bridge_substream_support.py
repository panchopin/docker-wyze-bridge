#!/usr/bin/env python3

import os
import pathlib
import sys
import unittest
import types
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(
    0, str(pathlib.Path(__file__).resolve().parent.parent / ".ha_live_addon" / "app")
)

if not hasattr(sys.modules.get("wyzebridge.wyze_stream"), "StreamStatus"):
    for module_name in list(sys.modules):
        if module_name == "wyzebridge" or module_name.startswith("wyzebridge."):
            del sys.modules[module_name]

sys.modules.setdefault("xxtea", types.ModuleType("xxtea"))

fake_wyzecam_iotc = types.ModuleType("wyzecam.iotc")
fake_wyzecam_iotc.WyzeIOTC = object
fake_wyzecam_iotc.WyzeIOTCSession = object
sys.modules.setdefault("wyzecam.iotc", fake_wyzecam_iotc)

from wyzecam.api_models import WyzeCamera
from wyzebridge.wyze_stream import StreamStatus, WyzeStream
from wyzebridge.wyze_stream_options import WyzeStreamOptions


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


class TestBridgeSubstreamSupport(unittest.TestCase):
    def test_kvs_camera_exposes_bridge_substream_even_without_firmware_map(self):
        camera = make_camera("HL_CAM4")

        self.assertFalse(camera.can_substream)
        self.assertTrue(camera.bridge_can_substream)

        with patch("wyzebridge.wyze_stream.publish_discovery"):
            stream = WyzeStream(
                SimpleNamespace(),
                SimpleNamespace(),
                camera,
                WyzeStreamOptions(quality="sd30", substream=True, reconnect=True),
            )

        self.assertNotEqual(stream.state, StreamStatus.DISABLED)
        self.assertFalse(stream.uses_kvs_source)
        self.assertTrue(stream.uses_tutk_source)

    def test_kvs_main_stream_still_uses_kvs_proxy(self):
        camera = make_camera("HL_CAM4")
        api = SimpleNamespace(setup_mtx_proxy=lambda uri: True)

        with (
            patch("wyzebridge.wyze_stream.publish_discovery"),
            patch.dict(os.environ, {"HL_CAM4_MAIN_PROBE_MODE": "kvs"}, clear=False),
        ):
            stream = WyzeStream(
                SimpleNamespace(),
                api,
                camera,
                WyzeStreamOptions(quality="hd180", reconnect=True),
            )
            self.assertTrue(stream.uses_kvs_source)
            self.assertFalse(stream.uses_tutk_source)

    def test_hl_cam4_main_probe_mode_can_switch_to_tutk(self):
        camera = make_camera("HL_CAM4")
        api = SimpleNamespace(setup_mtx_proxy=lambda uri: True)

        with (
            patch("wyzebridge.wyze_stream.publish_discovery"),
            patch.dict(os.environ, {"HL_CAM4_MAIN_PROBE_MODE": "tutk_dtls"}, clear=False),
        ):
            stream = WyzeStream(
                SimpleNamespace(),
                api,
                camera,
                WyzeStreamOptions(quality="hd180", reconnect=True),
            )
            self.assertFalse(stream.uses_kvs_source)
            self.assertTrue(stream.uses_tutk_source)

    def test_hl_cam4_main_probe_mode_defaults_back_to_kvs(self):
        camera = make_camera("HL_CAM4")

        with (
            patch("wyzebridge.wyze_stream.publish_discovery"),
            patch.dict(os.environ, {"HL_CAM4_MAIN_PROBE_MODE": "banana"}, clear=False),
        ):
            stream = WyzeStream(
                SimpleNamespace(),
                SimpleNamespace(setup_mtx_proxy=lambda uri: True),
                camera,
                WyzeStreamOptions(quality="hd180", reconnect=True),
            )
            self.assertTrue(stream.uses_kvs_source)
            self.assertFalse(stream.uses_tutk_source)

    def test_hl_cam4_substream_start_prefers_tutk_process(self):
        camera = make_camera("HL_CAM4")
        process = SimpleNamespace(start=lambda: None, is_alive=lambda: True)

        with (
            patch("wyzebridge.wyze_stream.publish_discovery"),
            patch("wyzebridge.wyze_stream.mp.Process", return_value=process) as proc_cls,
        ):
            stream = WyzeStream(
                SimpleNamespace(),
                SimpleNamespace(setup_mtx_proxy=lambda uri: False),
                camera,
                WyzeStreamOptions(quality="sd30", substream=True, reconnect=True),
            )
            started = stream.start()

        self.assertTrue(started)
        proc_cls.assert_called_once()
        self.assertIs(stream.tutk_stream_process, process)

    def test_v3_substream_stays_on_kvs_path(self):
        camera = make_camera("WYZE_CAKP2JFUS", "Deck")

        with patch("wyzebridge.wyze_stream.publish_discovery"):
            stream = WyzeStream(
                SimpleNamespace(),
                SimpleNamespace(setup_mtx_proxy=lambda uri: True),
                camera,
                WyzeStreamOptions(quality="sd30", substream=True, reconnect=True),
            )

        self.assertTrue(camera.can_substream)
        self.assertFalse(stream.uses_tutk_source)
        self.assertTrue(stream.uses_kvs_source)

    def test_hl_cam3p_kvs_substream_prefers_tutk_path(self):
        camera = make_camera("HL_CAM3P", "Hamster")
        camera.firmware_ver = "4.58.11.1234"

        with patch("wyzebridge.wyze_stream.publish_discovery"):
            stream = WyzeStream(
                SimpleNamespace(),
                SimpleNamespace(setup_mtx_proxy=lambda uri: True),
                camera,
                WyzeStreamOptions(quality="sd30", substream=True, reconnect=True),
            )

        self.assertTrue(camera.can_substream)
        self.assertTrue(stream.uses_tutk_source)
        self.assertFalse(stream.uses_kvs_source)

    def test_non_kvs_camera_without_substream_support_stays_blocked(self):
        camera = make_camera("WYZEC1", "Old Cam")

        self.assertFalse(camera.can_substream)
        self.assertFalse(camera.bridge_can_substream)


if __name__ == "__main__":
    unittest.main()

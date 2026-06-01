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

fake_wyzecam_tutk_pkg = types.ModuleType("wyzecam.tutk")
fake_wyzecam_tutk = types.ModuleType("wyzecam.tutk.tutk")
fake_wyzecam_tutk_protocol = types.ModuleType("wyzecam.tutk.tutk_protocol")
fake_wyzecam_tutk_ioctl_mux = types.ModuleType("wyzecam.tutk.tutk_ioctl_mux")
fake_wyzecam_tutk.FRAME_SIZE_2K = 4
fake_wyzecam_tutk.FRAME_SIZE_1080P = 3
fake_wyzecam_tutk.FRAME_SIZE_360P = 1
fake_wyzecam_tutk.FRAME_SIZE_DOORBELL_HD = 6
fake_wyzecam_tutk.FRAME_SIZE_DOORBELL_SD = 7
fake_wyzecam_tutk.TutkError = type("TutkError", (Exception,), {})
fake_wyzecam_tutk_pkg.tutk = fake_wyzecam_tutk
fake_wyzecam_tutk_pkg.tutk_protocol = fake_wyzecam_tutk_protocol
fake_wyzecam_tutk_pkg.tutk_ioctl_mux = fake_wyzecam_tutk_ioctl_mux


def _fake_tutk_protocol_attr(name: str):
    if name == "logger":
        return SimpleNamespace(setLevel=lambda *args, **kwargs: None)
    return type(name, (), {})


fake_wyzecam_tutk_protocol.__getattr__ = _fake_tutk_protocol_attr
fake_wyzecam_tutk_ioctl_mux.TutkIOCtlMux = type("TutkIOCtlMux", (), {})
sys.modules.setdefault("wyzecam.tutk", fake_wyzecam_tutk_pkg)
tutk_module = sys.modules.setdefault("wyzecam.tutk.tutk", fake_wyzecam_tutk)
sys.modules.setdefault("wyzecam.tutk.tutk_protocol", fake_wyzecam_tutk_protocol)
sys.modules.setdefault("wyzecam.tutk.tutk_ioctl_mux", fake_wyzecam_tutk_ioctl_mux)
for name in (
    "FRAME_SIZE_2K",
    "FRAME_SIZE_1080P",
    "FRAME_SIZE_360P",
    "FRAME_SIZE_DOORBELL_HD",
    "FRAME_SIZE_DOORBELL_SD",
    "TutkError",
):
    setattr(tutk_module, name, getattr(fake_wyzecam_tutk, name))

from wyzecam.api_models import WyzeCamera
import wyzebridge.wyze_stream as wyze_stream_module
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

        with patch.object(wyze_stream_module, "publish_discovery"):
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
            patch.object(wyze_stream_module, "publish_discovery"),
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
            patch.object(wyze_stream_module, "publish_discovery"),
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
            patch.object(wyze_stream_module, "publish_discovery"),
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
            patch.object(wyze_stream_module, "publish_discovery"),
            patch.object(wyze_stream_module.mp, "Process", return_value=process) as proc_cls,
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

        with patch.object(wyze_stream_module, "publish_discovery"):
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

        with patch.object(wyze_stream_module, "publish_discovery"):
            stream = WyzeStream(
                SimpleNamespace(),
                SimpleNamespace(setup_mtx_proxy=lambda uri: True),
                camera,
                WyzeStreamOptions(quality="sd30", substream=True, reconnect=True),
            )

        self.assertTrue(camera.can_substream)
        self.assertTrue(stream.uses_tutk_source)
        self.assertFalse(stream.uses_kvs_source)

    def test_hl_bc_explicit_substream_uses_kvs_path(self):
        camera = make_camera("HL_BC", "South Yard")

        self.assertFalse(camera.can_substream)
        self.assertTrue(camera.bridge_can_substream)

        with patch.object(wyze_stream_module, "publish_discovery"):
            stream = WyzeStream(
                SimpleNamespace(),
                SimpleNamespace(setup_mtx_proxy=lambda uri: True),
                camera,
                WyzeStreamOptions(quality="sd30", substream=True, reconnect=True),
            )

        self.assertNotEqual(stream.state, StreamStatus.DISABLED)
        self.assertFalse(stream.uses_tutk_source)
        self.assertTrue(stream.uses_kvs_source)

    def test_non_kvs_camera_without_substream_support_stays_blocked(self):
        camera = make_camera("WYZEC1", "Old Cam")

        self.assertFalse(camera.can_substream)
        self.assertFalse(camera.bridge_can_substream)


if __name__ == "__main__":
    unittest.main()

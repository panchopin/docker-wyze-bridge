#!/usr/bin/env python3

import pathlib
import sys
import unittest
import importlib
import types
from dataclasses import dataclass
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(
    0, str(pathlib.Path(__file__).resolve().parent.parent / ".ha_live_addon" / "app")
)

sys.modules.setdefault("yaml", types.ModuleType("yaml"))
sys.modules.setdefault("xxtea", types.ModuleType("xxtea"))

fake_wyzecam_iotc = types.ModuleType("wyzecam.iotc")
fake_wyzecam_iotc.WyzeIOTC = object
fake_wyzecam_iotc.WyzeIOTCSession = object
sys.modules.setdefault("wyzecam.iotc", fake_wyzecam_iotc)

fake_wyzecam_tutk = types.ModuleType("wyzecam.tutk")
fake_wyzecam_tutk_tutk = types.ModuleType("wyzecam.tutk.tutk")
fake_wyzecam_tutk_protocol = types.ModuleType("wyzecam.tutk.tutk_protocol")


class FakeTutkError(Exception):
    pass


class FakeTutkProtocolMessage:
    def __init__(self, *args, **kwargs):
        pass


class FakeTutkWyzeProtocolError(Exception):
    pass


fake_wyzecam_tutk_tutk.TutkError = FakeTutkError
fake_wyzecam_tutk.tutk = fake_wyzecam_tutk_tutk
fake_wyzecam_tutk.tutk_protocol = fake_wyzecam_tutk_protocol
for _name in (
    "K10058TakePhoto",
    "K10148StartBoa",
    "K11010GetCruisePoints",
    "K11018SetPTZPosition",
):
    setattr(fake_wyzecam_tutk_protocol, _name, FakeTutkProtocolMessage)
fake_wyzecam_tutk_protocol.TutkWyzeProtocolError = FakeTutkWyzeProtocolError
sys.modules.setdefault("wyzecam.tutk", fake_wyzecam_tutk)
sys.modules.setdefault("wyzecam.tutk.tutk", fake_wyzecam_tutk_tutk)
sys.modules.setdefault("wyzecam.tutk.tutk_protocol", fake_wyzecam_tutk_protocol)

for module_name in list(sys.modules):
    if module_name == "wyzebridge" or module_name.startswith("wyzebridge."):
        del sys.modules[module_name]


STUBBED_WYZECAM_MODULES = {
    "wyzecam.iotc",
    "wyzecam.tutk",
    "wyzecam.tutk.tutk",
    "wyzecam.tutk.tutk_protocol",
}


def reset_wyzecam_modules():
    for module_name in list(sys.modules):
        if module_name == "wyzecam" or module_name.startswith("wyzecam."):
            if module_name not in STUBBED_WYZECAM_MODULES:
                del sys.modules[module_name]

def make_camera(model: str = "HL_CAM4", nickname: str = "North Yard"):
    return SimpleNamespace(
        name_uri="north-yard",
        nickname=nickname,
        product_model=model,
        is_kvs=True,
        bridge_can_substream=True,
        camera_info=None,
    )


class FakeStream:
    def __init__(self, user, api, camera, options):
        self.user = user
        self.api = api
        self.camera = camera
        self.options = options
        self.uri = camera.name_uri + ("-sub" if options.substream else "")
        self.uses_kvs_source = not options.substream


@dataclass
class FakeWyzeStreamOptions:
    quality: str = "hd180"
    audio: bool = False
    record: bool = False
    reconnect: bool = True
    substream: bool = False


fake_wyzebridge_wyze_stream = types.ModuleType("wyzebridge.wyze_stream")
fake_wyzebridge_wyze_stream.WyzeStream = FakeStream
fake_wyzebridge_wyze_stream.WyzeStreamOptions = FakeWyzeStreamOptions
fake_wyzebridge_wyze_events = types.ModuleType("wyzebridge.wyze_events")
fake_wyzebridge_wyze_events.WyzeEvents = object
sys.modules["wyzebridge.wyze_stream"] = fake_wyzebridge_wyze_stream
sys.modules["wyzebridge.wyze_events"] = fake_wyzebridge_wyze_events


def fake_native_stream_info(camera, substream=False):
    return {
        "native_supported": True,
        "native_selected": camera.product_model == "HL_CAM4" and not substream,
        "native_reason": "",
        "native_alias": camera.name_uri + ("-sd" if substream else ""),
        "native_rtsp_url": "",
        "native_preload": False,
        "native_api_reachable": True,
        "snapshot_source": "go2rtc" if camera.product_model == "HL_CAM4" and not substream else "rtsp",
        "talkback_supported": False,
        "talkback_reason": "",
        "talkback_alias": camera.name_uri,
        "talkback_source": None,
    }


class FakeMtx:
    def __init__(self):
        self.paths = []

    def add_path(self, uri, on_demand, is_kvs):
        self.paths.append((uri, on_demand, is_kvs))

    def record(self, uri):
        raise AssertionError("record() should not be called in this test")


class FakeStreams:
    def __init__(self):
        self.added = []

    @property
    def total(self):
        return len(self.added)

    def add(self, stream):
        self.added.append(stream)

    def get_info(self, _uri):
        return {}

    def monitor_streams(self, _health_check):
        return None


class TestBridgeKVSStartupBehavior(unittest.TestCase):
    def test_initialize_does_not_exit_when_only_native_feeds_are_enabled(self):
        sys.modules.pop("wyze_bridge", None)
        reset_wyzecam_modules()
        with patch("os.makedirs"):
            wyze_bridge = importlib.import_module("wyze_bridge")
            WyzeBridge = wyze_bridge.WyzeBridge

        bridge = WyzeBridge.__new__(WyzeBridge)
        bridge.api = SimpleNamespace(
            login=lambda fresh_data=False: None,
            get_user=lambda: SimpleNamespace(email="test@example.com"),
            creds=SimpleNamespace(email="test@example.com"),
            filtered_cams=lambda: [make_camera()],
            auth=SimpleNamespace(access_token="token"),
        )
        bridge.streams = FakeStreams()
        bridge.mtx = SimpleNamespace(
            setup_auth=lambda *_args: None,
            dump_config=lambda: "",
            start=lambda: None,
            health_check=lambda: None,
        )
        bridge.setup_streams = lambda _user=None: None
        bridge._has_enabled_native_feed = lambda: True

        with (
            patch("wyze_bridge.WbAuth.set_email", lambda *args, **kwargs: None),
            patch("wyze_bridge.signal.raise_signal", side_effect=AssertionError("should not exit")),
        ):
            bridge._initialize(False)

    def test_camera_feed_config_honors_explicit_hd_sd_env_defaults(self):
        sys.modules.pop("wyze_bridge", None)
        reset_wyzecam_modules()
        with patch("os.makedirs"):
            WyzeBridge = importlib.import_module("wyze_bridge").WyzeBridge

        bridge = WyzeBridge.__new__(WyzeBridge)
        bridge.camera_hd_supported = lambda camera: True
        bridge.camera_sd_supported = lambda camera: True
        bridge.camera_feed_resolution = (
            lambda camera, feed: "2560x1440" if feed == "hd" else "640x360"
        )

        with (
            patch("wyze_bridge.get_camera_setting", side_effect=lambda _cam, _key, default="": default),
            patch("wyze_bridge.native_stream_info", side_effect=fake_native_stream_info),
            patch.dict(
                "os.environ",
                {
                    "HD_NORTH_YARD": "False",
                    "SD_NORTH_YARD": "True",
                    "GO2RTC_RTSP_PORT": "19554",
                },
                clear=False,
            ),
        ):
            bridge.streams = FakeStreams()
            config = bridge.camera_feed_config(make_camera())

        self.assertEqual(config["mode"], "sub")
        self.assertFalse(config["feeds"]["hd"]["enabled"])
        self.assertTrue(config["feeds"]["sd"]["enabled"])
        self.assertEqual(config["feeds"]["sd"]["path"], "sub")

    def test_camera_feed_config_sd_only_forces_single_sd_feed(self):
        sys.modules.pop("wyze_bridge", None)
        reset_wyzecam_modules()
        with patch("os.makedirs"):
            WyzeBridge = importlib.import_module("wyze_bridge").WyzeBridge

        bridge = WyzeBridge.__new__(WyzeBridge)
        bridge.camera_feed_resolution = (
            lambda camera, feed: "2560x1440" if feed == "hd" else "640x360"
        )

        def saved_setting(_cam, key, default=""):
            return {"hd": True, "sd": False}.get(key, default)

        with (
            patch("wyze_bridge.get_camera_setting", side_effect=saved_setting),
            patch("wyze_bridge.native_stream_info", side_effect=fake_native_stream_info),
            patch.dict("os.environ", {"SD_ONLY": "true", "GO2RTC_RTSP_PORT": "19554"}, clear=False),
        ):
            bridge.streams = FakeStreams()
            config = bridge.camera_feed_config(make_camera())

        self.assertTrue(config["sd_only"])
        self.assertEqual(config["mode"], "sub")
        self.assertFalse(config["feeds"]["hd"]["enabled"])
        self.assertFalse(config["feeds"]["hd"]["supported"])
        self.assertIn("SD_ONLY", config["feeds"]["hd"]["reason"])
        self.assertTrue(config["feeds"]["sd"]["enabled"])

    def test_apply_camera_stream_config_rejects_hd_when_sd_only(self):
        sys.modules.pop("wyze_bridge", None)
        reset_wyzecam_modules()
        with patch("os.makedirs"):
            WyzeBridge = importlib.import_module("wyze_bridge").WyzeBridge

        bridge = WyzeBridge.__new__(WyzeBridge)
        bridge.camera_feed_resolution = (
            lambda camera, feed: "2560x1440" if feed == "hd" else "640x360"
        )

        with (
            patch("wyze_bridge.get_camera_setting", side_effect=lambda _cam, _key, default="": default),
            patch("wyze_bridge.native_stream_info", side_effect=fake_native_stream_info),
            patch.dict("os.environ", {"SD_ONLY": "true"}, clear=False),
        ):
            bridge.streams = FakeStreams()
            with self.assertRaisesRegex(ValueError, "SD_ONLY"):
                bridge.apply_camera_stream_config(
                    make_camera(),
                    {"hd_enabled": True, "sd_enabled": True, "hd_kbps": 180, "sd_kbps": 30},
                )

    def test_camera_feed_config_keeps_hl_bc_sd_on_main_path(self):
        sys.modules.pop("wyze_bridge", None)
        reset_wyzecam_modules()
        with patch("os.makedirs"):
            WyzeBridge = importlib.import_module("wyze_bridge").WyzeBridge

        bridge = WyzeBridge.__new__(WyzeBridge)
        bridge.camera_feed_resolution = (
            lambda camera, feed: "2560x1440" if feed == "hd" else "640x360"
        )

        with (
            patch("wyze_bridge.get_camera_setting", side_effect=lambda _cam, _key, default="": default),
            patch("wyze_bridge.native_stream_info", side_effect=fake_native_stream_info),
            patch.dict(
                "os.environ",
                {
                    "HD_NORTH_YARD": "False",
                    "SD_NORTH_YARD": "True",
                    "GO2RTC_RTSP_PORT": "19554",
                },
                clear=False,
            ),
        ):
            bridge.streams = FakeStreams()
            config = bridge.camera_feed_config(make_camera(model="HL_BC", nickname="South Yard"))

        self.assertEqual(config["mode"], "sub")
        self.assertFalse(config["feeds"]["hd"]["enabled"])
        self.assertTrue(config["feeds"]["sd"]["enabled"])
        self.assertEqual(config["feeds"]["sd"]["path"], "main")

    def test_camera_feed_config_lets_explicit_env_override_saved_feed_settings(self):
        sys.modules.pop("wyze_bridge", None)
        reset_wyzecam_modules()
        with patch("os.makedirs"):
            wyze_bridge = importlib.import_module("wyze_bridge")
            WyzeBridge = wyze_bridge.WyzeBridge

        bridge = WyzeBridge.__new__(WyzeBridge)
        bridge.camera_hd_supported = lambda camera: True
        bridge.camera_sd_supported = lambda camera: True
        bridge.camera_feed_resolution = (
            lambda camera, feed: "2560x1440" if feed == "hd" else "640x360"
        )

        with (
            patch(
                "wyze_bridge.get_camera_setting",
                side_effect=lambda _cam, key, default="": {
                    "hd": "",
                    "sd": "1",
                }.get(key, default),
            ),
            patch("wyze_bridge.native_stream_info", side_effect=fake_native_stream_info),
            patch.dict(
                "os.environ",
                {
                    "HD_NORTH_YARD": "True",
                    "SD_NORTH_YARD": "False",
                    "GO2RTC_RTSP_PORT": "19554",
                },
                clear=False,
            ),
        ):
            bridge.streams = FakeStreams()
            config = bridge.camera_feed_config(make_camera())

        self.assertEqual(config["mode"], "main")
        self.assertTrue(config["feeds"]["hd"]["enabled"])
        self.assertFalse(config["feeds"]["sd"]["enabled"])
        self.assertEqual(config["feeds"]["hd"]["path"], "native")

    def test_camera_feed_config_defaults_to_sd_when_both_feeds_disabled(self):
        sys.modules.pop("wyze_bridge", None)
        reset_wyzecam_modules()
        with patch("os.makedirs"):
            WyzeBridge = importlib.import_module("wyze_bridge").WyzeBridge

        bridge = WyzeBridge.__new__(WyzeBridge)
        bridge.camera_hd_supported = lambda camera: True
        bridge.camera_sd_supported = lambda camera: True
        bridge.camera_feed_resolution = (
            lambda camera, feed: "2560x1440" if feed == "hd" else "640x360"
        )

        with (
            patch(
                "wyze_bridge.get_camera_setting",
                side_effect=lambda _cam, key, default="": {
                    "hd": "",
                    "sd": "",
                }.get(key, default),
            ),
            patch("wyze_bridge.native_stream_info", side_effect=fake_native_stream_info),
            patch.dict(
                "os.environ",
                {
                    "HD_NORTH_YARD": "False",
                    "SD_NORTH_YARD": "False",
                    "GO2RTC_RTSP_PORT": "19554",
                },
                clear=False,
            ),
        ):
            bridge.streams = FakeStreams()
            config = bridge.camera_feed_config(make_camera())

        self.assertEqual(config["mode"], "sub")
        self.assertFalse(config["feeds"]["hd"]["enabled"])
        self.assertTrue(config["feeds"]["sd"]["enabled"])
        self.assertEqual(config["feeds"]["sd"]["path"], "sub")

    def test_camera_feed_config_falls_back_to_bridge_sub_when_go2rtc_unreachable_for_native_sd(self):
        # Verify the SD feed falls back to bridge-sub when native_selected=False.
        # After the 4.2.9 fix, native_selected=False only happens when go2rtc is fully
        # unreachable (not merely because the alias hasn't been probed yet).
        sys.modules.pop("wyze_bridge", None)
        reset_wyzecam_modules()
        with patch("os.makedirs"):
            WyzeBridge = importlib.import_module("wyze_bridge").WyzeBridge

        bridge = WyzeBridge.__new__(WyzeBridge)
        bridge.camera_hd_supported = lambda camera: True
        bridge.camera_sd_supported = lambda camera: True
        bridge.camera_feed_resolution = (
            lambda camera, feed: "2560x1440" if feed == "hd" else "640x360"
        )

        def fake_broken_native_stream_info(camera, substream=False):
            info = fake_native_stream_info(camera, substream=substream)
            if substream:
                info["native_selected"] = False
                info["native_alias_ready"] = False
                info["native_reason"] = "HL_CAM3P validated on native go2rtc for the SD feed; go2rtc sidecar is not reachable"
                info["snapshot_source"] = "rtsp"
            return info

        with (
            patch(
                "wyze_bridge.get_camera_setting",
                side_effect=lambda _cam, key, default="": {
                    "stream": "sub",
                    "hd": "",
                    "sd": "1",
                }.get(key, default),
            ),
            patch("wyze_bridge.native_stream_info", side_effect=fake_broken_native_stream_info),
            patch.dict("os.environ", {"GO2RTC_RTSP_PORT": "19554"}, clear=False),
        ):
            bridge.streams = FakeStreams()
            config = bridge.camera_feed_config(make_camera())

        self.assertEqual(config["mode"], "sub")
        self.assertFalse(config["feeds"]["hd"]["enabled"])
        self.assertEqual(config["feeds"]["sd"]["path"], "sub")

    def test_camera_feed_config_keeps_native_sd_alias_for_hl_cam4_preview_refresh(self):
        sys.modules.pop("wyze_bridge", None)
        reset_wyzecam_modules()
        with patch("os.makedirs"):
            WyzeBridge = importlib.import_module("wyze_bridge").WyzeBridge

        bridge = WyzeBridge.__new__(WyzeBridge)
        bridge.camera_hd_supported = lambda camera: True
        bridge.camera_sd_supported = lambda camera: True
        bridge.camera_feed_resolution = (
            lambda camera, feed: "2560x1440" if feed == "hd" else "640x360"
        )

        def fake_dual_native_stream_info(camera, substream=False):
            info = fake_native_stream_info(camera, substream=substream)
            info["native_selected"] = False
            info["snapshot_source"] = "rtsp"
            return info

        with (
            patch("wyze_bridge.get_camera_setting", side_effect=lambda _cam, _key, default="": default),
            patch("wyze_bridge.native_stream_info", side_effect=fake_dual_native_stream_info),
            patch.dict("os.environ", {"GO2RTC_RTSP_PORT": "19554"}, clear=False),
        ):
            bridge.streams = FakeStreams()
            config = bridge.camera_feed_config(make_camera())

        self.assertEqual(config["mode"], "main")
        self.assertEqual(config["feeds"]["hd"]["path"], "main")
        self.assertFalse(config["feeds"]["sd"]["enabled"])
        self.assertTrue(config["native_preview_sd"])

    def test_setup_streams_does_not_eagerly_start_kvs_proxy(self):
        sys.modules.pop("wyze_bridge", None)
        reset_wyzecam_modules()
        with patch("os.makedirs"):
            WyzeBridge = importlib.import_module("wyze_bridge").WyzeBridge

        bridge = WyzeBridge.__new__(WyzeBridge)
        bridge.api = SimpleNamespace(
            get_user=lambda: SimpleNamespace(email="test@example.com"),
            filtered_cams=lambda: [make_camera()],
            setup_mtx_proxy=lambda uri: (_ for _ in ()).throw(AssertionError("setup_mtx_proxy should not run during setup_streams")),
        )
        bridge.streams = FakeStreams()
        bridge.mtx = FakeMtx()
        bridge.add_substream = lambda user, api, cam, options: None

        with (
            patch("wyze_bridge.WyzeStream", FakeStream),
            patch("wyze_bridge.env_cam", side_effect=lambda key, name_uri, default=None, style="": default),
            patch("wyze_bridge.is_livestream", return_value=False),
            patch("wyze_bridge.ON_DEMAND", True),
        ):
            bridge.setup_streams(SimpleNamespace(email="test@example.com"))

        self.assertEqual(len(bridge.streams.added), 1)
        self.assertEqual(bridge.streams.added[0].uri, "north-yard")
        self.assertEqual(bridge.mtx.paths, [("north-yard", True, True)])

    def test_setup_streams_honors_sub_only_mode(self):
        sys.modules.pop("wyze_bridge", None)
        reset_wyzecam_modules()
        with patch("os.makedirs"):
            wyze_bridge = importlib.import_module("wyze_bridge")
            WyzeBridge = wyze_bridge.WyzeBridge

        bridge = WyzeBridge.__new__(WyzeBridge)
        bridge.api = SimpleNamespace(
            get_user=lambda: SimpleNamespace(email="test@example.com"),
            filtered_cams=lambda: [make_camera()],
        )
        bridge.streams = FakeStreams()
        bridge.mtx = FakeMtx()

        with (
            patch("wyze_bridge.WyzeStream", FakeStream),
            patch(
                "wyze_bridge.get_camera_setting",
                side_effect=lambda _cam, key, default="": "sub" if key == "stream" else default,
            ),
            patch("wyze_bridge.native_stream_info", side_effect=fake_native_stream_info),
            patch.dict("os.environ", {"GO2RTC_RTSP_PORT": "19554"}, clear=False),
            patch("wyze_bridge.env_cam", side_effect=lambda key, name_uri, default=None, style="": default),
            patch("wyze_bridge.is_livestream", return_value=False),
            patch("wyze_bridge.ON_DEMAND", True),
        ):
            bridge.setup_streams(SimpleNamespace(email="test@example.com"))

        self.assertEqual(len(bridge.streams.added), 1)
        self.assertEqual(bridge.streams.added[0].uri, "north-yard-sub")
        self.assertEqual(bridge.mtx.paths, [("north-yard-sub", True, False)])

    def test_setup_streams_sd_only_creates_one_sd_stream(self):
        sys.modules.pop("wyze_bridge", None)
        reset_wyzecam_modules()
        with patch("os.makedirs"):
            wyze_bridge = importlib.import_module("wyze_bridge")
            WyzeBridge = wyze_bridge.WyzeBridge

        bridge = WyzeBridge.__new__(WyzeBridge)
        bridge.api = SimpleNamespace(
            get_user=lambda: SimpleNamespace(email="test@example.com"),
            filtered_cams=lambda: [make_camera()],
        )
        bridge.streams = FakeStreams()
        bridge.mtx = FakeMtx()

        with (
            patch("wyze_bridge.WyzeStream", FakeStream),
            patch("wyze_bridge.native_stream_info", side_effect=fake_native_stream_info),
            patch("wyze_bridge.get_camera_setting", side_effect=lambda _cam, _key, default="": default),
            patch("wyze_bridge.env_cam", side_effect=lambda key, name_uri, default=None, style="": default),
            patch("wyze_bridge.is_livestream", return_value=False),
            patch("wyze_bridge.ON_DEMAND", True),
            patch.dict("os.environ", {"SD_ONLY": "true", "GO2RTC_RTSP_PORT": "19554"}, clear=False),
        ):
            bridge.setup_streams(SimpleNamespace(email="test@example.com"))

        self.assertEqual(len(bridge.streams.added), 1)
        self.assertEqual(bridge.streams.added[0].uri, "north-yard-sub")
        self.assertEqual(bridge.streams.added[0].options.quality, "sd30")
        self.assertEqual(bridge.mtx.paths, [("north-yard-sub", True, False)])

    def test_setup_streams_honors_both_mode(self):
        sys.modules.pop("wyze_bridge", None)
        reset_wyzecam_modules()
        with patch("os.makedirs"):
            wyze_bridge = importlib.import_module("wyze_bridge")
            WyzeBridge = wyze_bridge.WyzeBridge

        bridge = WyzeBridge.__new__(WyzeBridge)
        bridge.api = SimpleNamespace(
            get_user=lambda: SimpleNamespace(email="test@example.com"),
            filtered_cams=lambda: [make_camera()],
        )
        bridge.streams = FakeStreams()
        bridge.mtx = FakeMtx()

        with (
            patch("wyze_bridge.WyzeStream", FakeStream),
            patch(
                "wyze_bridge.get_camera_setting",
                side_effect=lambda _cam, key, default="": "both" if key == "stream" else default,
            ),
            patch("wyze_bridge.native_stream_info", side_effect=fake_native_stream_info),
            patch.dict("os.environ", {"GO2RTC_RTSP_PORT": "19554"}, clear=False),
            patch("wyze_bridge.env_cam", side_effect=lambda key, name_uri, default=None, style="": default),
            patch("wyze_bridge.is_livestream", return_value=False),
            patch("wyze_bridge.ON_DEMAND", True),
        ):
            bridge.setup_streams(SimpleNamespace(email="test@example.com"))

        self.assertEqual(len(bridge.streams.added), 1)
        self.assertEqual(bridge.streams.added[0].uri, "north-yard-sub")
        self.assertEqual(bridge.mtx.paths, [("north-yard-sub", True, False)])

    def test_setup_streams_skips_bridge_substream_for_native_sd_feed(self):
        sys.modules.pop("wyze_bridge", None)
        reset_wyzecam_modules()
        with patch("os.makedirs"):
            wyze_bridge = importlib.import_module("wyze_bridge")
            WyzeBridge = wyze_bridge.WyzeBridge

        bridge = WyzeBridge.__new__(WyzeBridge)
        bridge.api = SimpleNamespace(
            get_user=lambda: SimpleNamespace(email="test@example.com"),
            filtered_cams=lambda: [make_camera()],
        )
        bridge.streams = FakeStreams()
        bridge.mtx = FakeMtx()
        bridge.camera_stream_config = lambda _cam: {
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
                    "path": "native",
                    "reason": "",
                },
            },
        }
        bridge.add_substream = lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("bridge substream should not be created for native SD feeds")
        )

        with (
            patch("wyze_bridge.WyzeStream", FakeStream),
            patch("wyze_bridge.env_cam", side_effect=lambda key, name_uri, default=None, style="": default),
            patch("wyze_bridge.native_stream_info", side_effect=fake_native_stream_info),
            patch.dict("os.environ", {"GO2RTC_RTSP_PORT": "19554"}, clear=False),
            patch("wyze_bridge.is_livestream", return_value=False),
            patch("wyze_bridge.ON_DEMAND", True),
        ):
            bridge.setup_streams(SimpleNamespace(email="test@example.com"))

        self.assertEqual([stream.uri for stream in bridge.streams.added], ["north-yard"])
        self.assertEqual(bridge.mtx.paths, [("north-yard", True, True)])

    def test_setup_streams_creates_main_stream_for_sd_only_main_path(self):
        sys.modules.pop("wyze_bridge", None)
        reset_wyzecam_modules()
        with patch("os.makedirs"):
            wyze_bridge = importlib.import_module("wyze_bridge")
            WyzeBridge = wyze_bridge.WyzeBridge

        bridge = WyzeBridge.__new__(WyzeBridge)
        bridge.api = SimpleNamespace(
            get_user=lambda: SimpleNamespace(email="test@example.com"),
            filtered_cams=lambda: [make_camera(model="HL_BC", nickname="South Yard")],
        )
        bridge.streams = FakeStreams()
        bridge.mtx = FakeMtx()
        bridge.camera_stream_config = lambda _cam: {
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
        bridge.add_substream = lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("bridge substream should not be created for main-path SD feeds")
        )

        with (
            patch("wyze_bridge.WyzeStream", FakeStream),
            patch("wyze_bridge.env_cam", side_effect=lambda key, name_uri, default=None, style="": default),
            patch("wyze_bridge.is_livestream", return_value=False),
            patch("wyze_bridge.ON_DEMAND", True),
        ):
            bridge.setup_streams(SimpleNamespace(email="test@example.com"))

        self.assertEqual([stream.uri for stream in bridge.streams.added], ["north-yard"])
        self.assertEqual(bridge.streams.added[0].options.quality, "sd30")
        self.assertEqual(bridge.mtx.paths, [("north-yard", True, True)])

    def test_sd_only_kvs_camera_uses_bridge_main_when_native_sd_alias_not_ready(self):
        sys.modules.pop("wyze_bridge", None)
        reset_wyzecam_modules()
        with patch("os.makedirs"):
            wyze_bridge = importlib.import_module("wyze_bridge")
            WyzeBridge = wyze_bridge.WyzeBridge

        bridge = WyzeBridge.__new__(WyzeBridge)
        bridge.streams = FakeStreams()
        camera = make_camera(model="HL_CAM3P", nickname="Hamster")
        camera.name_uri = "hamster"

        def native_info(_camera, substream=False):
            return {
                "native_supported": True,
                "native_selected": bool(substream),
                "native_alias": "hamster-sd" if substream else "hamster",
                "native_alias_ready": False,
                "native_api_reachable": True,
                "native_rtsp_url": "rtsp://127.0.0.1:19554/hamster-sd",
                "snapshot_source": "go2rtc",
            }

        with (
            patch("wyze_bridge.native_stream_info", side_effect=native_info),
            patch.dict("os.environ", {"SD_ONLY": "true", "GO2RTC_RTSP_PORT": "19554"}, clear=False),
            patch("wyze_bridge.env_cam", side_effect=lambda key, name_uri, default=None, style="": default),
            patch("wyze_bridge.get_camera_setting", side_effect=lambda _cam, _key, default="": default),
        ):
            config = bridge.camera_stream_config(camera)

        self.assertEqual(config["feeds"]["sd"]["path"], "main")
        self.assertTrue(config["feeds"]["sd"]["enabled"])
        self.assertFalse(config["feeds"]["hd"]["enabled"])

    def test_camera_substream_enabled_rejects_sub_mode_on_unsupported_camera(self):
        sys.modules.pop("wyze_bridge", None)
        reset_wyzecam_modules()
        with patch("os.makedirs"):
            WyzeBridge = importlib.import_module("wyze_bridge").WyzeBridge

        bridge = WyzeBridge.__new__(WyzeBridge)
        bridge.streams = FakeStreams()
        camera = make_camera()
        camera.bridge_can_substream = False

        self.assertFalse(bridge.camera_substream_enabled(camera, "sub"))

    def test_add_substream_registers_tutk_source_for_kvs_camera(self):
        sys.modules.pop("wyze_bridge", None)
        reset_wyzecam_modules()
        with patch("os.makedirs"):
            wyze_bridge = importlib.import_module("wyze_bridge")
            WyzeBridge = wyze_bridge.WyzeBridge

        bridge = WyzeBridge.__new__(WyzeBridge)
        bridge.streams = FakeStreams()
        bridge.mtx = FakeMtx()
        bridge.camera_substream_enabled = lambda _cam: True

        with (
            patch("wyze_bridge.WyzeStream", FakeStream),
            patch("wyze_bridge.env_bool", side_effect=lambda key, false="", true="", style="": key == "SUBSTREAM"),
            patch("wyze_bridge.env_cam", side_effect=lambda key, name_uri, default=None, style="": default),
        ):
            bridge.add_substream(
                SimpleNamespace(email="test@example.com"),
                SimpleNamespace(),
                make_camera(),
                wyze_bridge.WyzeStreamOptions(reconnect=False),
            )

        self.assertEqual(len(bridge.streams.added), 1)
        self.assertEqual(bridge.streams.added[0].uri, "north-yard-sub")
        self.assertEqual(bridge.mtx.paths, [("north-yard-sub", True, False)])


if __name__ == "__main__":
    unittest.main()

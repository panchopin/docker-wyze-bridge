#!/usr/bin/env python3

import io
import os
import pathlib
import sys
import tempfile
import types
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, call, patch

try:
    from PIL import Image
except ImportError:
    Image = None

original_requests_module = sys.modules.get("requests")
original_requests_exceptions_module = sys.modules.get("requests.exceptions")
original_wyzebridge_modules = {
    name: module
    for name, module in sys.modules.items()
    if name == "wyzebridge" or name.startswith("wyzebridge.")
}

requests_stub = types.ModuleType("requests")
requests_exceptions = types.ModuleType("requests.exceptions")
requests_stub.RequestException = Exception
requests_stub.PreparedRequest = Mock
requests_stub.Response = Mock
requests_stub.get = Mock()
requests_stub.put = Mock()
requests_stub.post = Mock()
requests_exceptions.ConnectionError = Exception
requests_exceptions.HTTPError = Exception
requests_exceptions.RequestException = Exception
requests_stub.exceptions = requests_exceptions
sys.modules["requests"] = requests_stub
sys.modules["requests.exceptions"] = requests_exceptions

# Stub native-only modules that can't be installed outside Docker
_paho = types.ModuleType("paho")
_paho_mqtt = types.ModuleType("paho.mqtt")
_paho_mqtt_client = types.ModuleType("paho.mqtt.client")
_paho_mqtt_publish = types.ModuleType("paho.mqtt.publish")
_paho_mqtt_client.Client = Mock
_paho_mqtt_client.CallbackAPIVersion = types.SimpleNamespace(VERSION2=2)
_paho_mqtt_publish.multiple = Mock()
_paho.mqtt = _paho_mqtt
_paho_mqtt.client = _paho_mqtt_client
_paho_mqtt.publish = _paho_mqtt_publish
for _mod_name, _mod in [
    ("paho", _paho),
    ("paho.mqtt", _paho_mqtt),
    ("paho.mqtt.client", _paho_mqtt_client),
    ("paho.mqtt.publish", _paho_mqtt_publish),
]:
    sys.modules.setdefault(_mod_name, _mod)

for _mod in ("xxtea",):
    sys.modules.setdefault(_mod, types.ModuleType(_mod))
# Stub wyzecam.iotc and tutk sub-hierarchy to avoid loading native .so files.
# Do NOT stub 'wyzecam' itself — the real package must be importable for api_models etc.
_wyzecam_iotc = types.ModuleType("wyzecam.iotc")
_wyzecam_iotc.WyzeIOTC = Mock
_wyzecam_iotc.WyzeIOTCSession = Mock
for _name, _mod in [
    ("wyzecam.iotc", _wyzecam_iotc),
    ("wyzecam.tutk", types.ModuleType("wyzecam.tutk")),
    ("wyzecam.tutk.tutk", types.ModuleType("wyzecam.tutk.tutk")),
    ("wyzecam.tutk.tutk_ioctl_mux", types.ModuleType("wyzecam.tutk.tutk_ioctl_mux")),
    ("wyzecam.tutk.tutk_protocol", types.ModuleType("wyzecam.tutk.tutk_protocol")),
]:
    sys.modules.setdefault(_name, _mod)

for module_name in list(sys.modules):
    if module_name == "wyzebridge" or module_name.startswith("wyzebridge."):
        del sys.modules[module_name]

# Re-apply wyzebridge internal stubs AFTER the clear so they aren't wiped out.
# stream_manager imports wyze_events → wyze_stream → wyzecam.tutk native .so,
# which cannot load outside Docker. Stub those two at the wyzebridge level.
_wyzebridge_wyze_stream = types.ModuleType("wyzebridge.wyze_stream")
_wyzebridge_wyze_stream.WyzeStream = Mock
_wyzebridge_wyze_events = types.ModuleType("wyzebridge.wyze_events")
_wyzebridge_wyze_events.WyzeEvents = Mock
sys.modules["wyzebridge.wyze_stream"] = _wyzebridge_wyze_stream
sys.modules["wyzebridge.wyze_events"] = _wyzebridge_wyze_events

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "app"))

import wyzebridge.bridge_diagnostics as bridge_diagnostics_module
import wyzebridge.ffmpeg as ffmpeg_module
import wyzebridge.go2rtc as go2rtc_module
import wyzebridge.stream_manager as stream_manager_module
from wyzebridge.bridge_diagnostics import collect_bridge_diagnostics
from wyzebridge.stream_manager import StreamManager

if original_requests_module is not None:
    sys.modules["requests"] = original_requests_module
else:
    sys.modules.pop("requests", None)

if original_requests_exceptions_module is not None:
    sys.modules["requests.exceptions"] = original_requests_exceptions_module
else:
    sys.modules.pop("requests.exceptions", None)

for module_name in list(sys.modules):
    if (
        module_name == "wyzebridge"
        or module_name.startswith("wyzebridge.")
    ) and module_name not in original_wyzebridge_modules:
        del sys.modules[module_name]

sys.modules.update(original_wyzebridge_modules)

# StreamManager import needed the lightweight wyzebridge stubs above, but later
# tests in the same pytest process need the real module. Drop the stubs after
# import so future imports resolve the actual implementation.
if "wyzebridge.wyze_stream" not in original_wyzebridge_modules:
    sys.modules.pop("wyzebridge.wyze_stream", None)
if "wyzebridge.wyze_events" not in original_wyzebridge_modules:
    sys.modules.pop("wyzebridge.wyze_events", None)


def valid_jpeg_bytes(color: tuple[int, int, int]) -> bytes:
    assert Image is not None
    image = Image.new("RGB", (48, 32), color)
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", quality=90)
    return buffer.getvalue()


class DummyApi:
    def get_camera(self, _cam_name):
        return None


class FakeSnapshotPopen:
    def __init__(self, cmd, stdout=None, stderr=None, stderr_output=b"", image_bytes=None):
        self.cmd = cmd
        self.stdout = stdout
        self.stderr = stderr
        self.returncode = 0
        self._stderr_output = stderr_output
        self._image_bytes = image_bytes or valid_jpeg_bytes((96, 144, 192))

    def communicate(self, timeout=None):
        with open(self.cmd[-1], "wb") as handle:
            handle.write(self._image_bytes)
        return b"", self._stderr_output

    def poll(self):
        return self.returncode

    def kill(self):
        self.returncode = -9


class FakeTimeoutPopen(FakeSnapshotPopen):
    def __init__(self, cmd, stdout=None, stderr=None):
        super().__init__(cmd, stdout=stdout, stderr=stderr)
        self.returncode = None

    def communicate(self, timeout=None):
        if self.returncode == -9:
            return b"", b""
        raise stream_manager_module.TimeoutExpired(self.cmd, timeout)


class TestGo2RtcSnapshotAndDiagnostics(unittest.TestCase):
    def tearDown(self):
        go2rtc_module._GO2RTC_API_REACHABLE_CACHE.clear()
        go2rtc_module._NATIVE_ALIAS_READY_CACHE.clear()
        requests_stub.get.reset_mock()
        requests_stub.get.side_effect = None
        requests_stub.put.reset_mock()
        requests_stub.post.reset_mock()

    def test_go2rtc_api_reachable_uses_short_cache(self):
        response = Mock()
        response.raise_for_status.return_value = None
        requests_stub.get.return_value = response

        self.assertTrue(go2rtc_module._go2rtc_api_reachable())
        self.assertTrue(go2rtc_module._go2rtc_api_reachable())

        requests_stub.get.assert_called_once_with(
            f"{go2rtc_module.go2rtc_api_base()}/api",
            timeout=0.75,
        )

    @patch.object(go2rtc_module, "_native_alias_is_ready")
    @patch.object(go2rtc_module, "_go2rtc_api_reachable")
    def test_native_stream_info_selected_when_api_reachable_even_if_alias_not_ready(
        self, mock_api_reachable, mock_alias_ready
    ):
        # alias_ready is diagnostic-only; it must NOT block selection when the sidecar is up.
        # Previously this gated native_selected=False, causing Scrypted to cache a bad URL
        # and HomeKit to lose the camera on every bridge restart (4.2.8 regression).
        mock_api_reachable.return_value = True
        mock_alias_ready.return_value = False
        camera = SimpleNamespace(name_uri="hamster", product_model="HL_CAM3P", is_gwell=False)

        info = go2rtc_module.native_stream_info(camera, substream=True)

        self.assertTrue(info["native_supported"])
        self.assertTrue(info["native_selected"])        # selected because api_reachable=True
        self.assertFalse(info["native_alias_ready"])    # diagnostic: alias not hot yet
        self.assertEqual(info["snapshot_source"], "go2rtc")
        self.assertNotIn("failed readiness check", info["native_reason"])
        self.assertFalse(info["talkback_supported"])    # substream — talkback always off
        mock_alias_ready.assert_called_once_with("hamster-sd")

    @patch.object(go2rtc_module, "_native_alias_is_ready")
    @patch.object(go2rtc_module, "_go2rtc_api_reachable")
    def test_native_stream_info_not_selected_when_go2rtc_unreachable(
        self, mock_api_reachable, mock_alias_ready
    ):
        # When the go2rtc sidecar is completely down the camera should be reported as
        # not-selected so Scrypted can surface it as offline rather than serve a dead URL.
        mock_api_reachable.return_value = False
        mock_alias_ready.return_value = False
        camera = SimpleNamespace(name_uri="north-yard", product_model="HL_CAM4", is_gwell=False)

        info = go2rtc_module.native_stream_info(camera, substream=False)

        self.assertTrue(info["native_supported"])
        self.assertFalse(info["native_selected"])
        self.assertFalse(info["native_alias_ready"])
        self.assertEqual(info["snapshot_source"], "rtsp")
        self.assertIn("not reachable", info["native_reason"])
        self.assertFalse(info["talkback_supported"])
        # alias readiness should NOT be checked when the API is down (avoids a wasted call)
        mock_alias_ready.assert_not_called()

    @patch.object(go2rtc_module, "_native_alias_is_ready")
    @patch.object(go2rtc_module, "_go2rtc_api_reachable")
    def test_hl_cam4_substream_native_selected_when_api_reachable(
        self, mock_api_reachable, mock_alias_ready
    ):
        mock_api_reachable.return_value = True
        mock_alias_ready.return_value = False
        camera = SimpleNamespace(name_uri="north-yard", product_model="HL_CAM4", is_gwell=False)

        info = go2rtc_module.native_stream_info(camera, substream=True)

        self.assertTrue(info["native_supported"])
        self.assertTrue(info["native_selected"])
        self.assertFalse(info["native_alias_ready"])
        self.assertEqual(info["native_alias"], "north-yard-sd")
        self.assertEqual(info["snapshot_source"], "go2rtc")

    def test_talkback_codec_probe_requests_microphone_media(self):
        response = Mock()
        response.json.return_value = {"producers": []}
        requests_stub.get.return_value = response

        go2rtc_module._go2rtc_stream_details("north-yard")

        requests_stub.get.assert_called_with(
            f"{go2rtc_module.go2rtc_api_base()}/api/streams",
            params={"src": "north-yard", "microphone": "any"},
            timeout=2.0,
        )

    def test_stream_details_falls_back_to_full_stream_table_when_src_probe_fails(self):
        full_response = Mock()
        full_response.raise_for_status.return_value = None
        full_response.json.return_value = {
            "sample-cam-sd": {
                "producers": [
                    {
                        "source": "wyze://192.0.2.175?mac=AABBCCDDEEFF&subtype=sd",
                        "receivers": [{"bytes": 648723}],
                    }
                ],
                "consumers": [],
            }
        }
        requests_stub.get.side_effect = [Exception("src probe timed out"), full_response]

        details = go2rtc_module._go2rtc_stream_details("sample-cam-sd")

        self.assertEqual(
            details["producers"][0]["source"],
            "wyze://192.0.2.175?mac=AABBCCDDEEFF&subtype=sd",
        )
        self.assertEqual(requests_stub.get.call_count, 2)
        requests_stub.get.assert_has_calls(
            [
                call(
                    f"{go2rtc_module.go2rtc_api_base()}/api/streams",
                    params={"src": "sample-cam-sd", "microphone": "any"},
                    timeout=2.0,
                ),
                call(
                    f"{go2rtc_module.go2rtc_api_base()}/api/streams",
                    timeout=2.0,
                ),
            ]
        )

    @patch.object(go2rtc_module.time, "sleep")
    @patch.object(go2rtc_module, "preload_native_stream")
    @patch.object(go2rtc_module, "_talkback_ffmpeg_codec")
    def test_talkback_codec_resolution_preloads_and_retries(
        self, mock_codec, mock_preload, _mock_sleep
    ):
        mock_codec.side_effect = [None, "aac/16000"]

        codec = go2rtc_module._resolve_talkback_ffmpeg_codec("north-yard")

        self.assertEqual(codec, "aac/16000")
        mock_preload.assert_called_once_with("north-yard", timeout=2.0)
        self.assertEqual(mock_codec.call_count, 2)

    @patch.object(go2rtc_module, "_resolve_talkback_ffmpeg_codec")
    @patch.object(go2rtc_module, "_go2rtc_stream_request")
    def test_send_native_talkback_uses_resolved_codec_for_audio_url(
        self, mock_stream_request, mock_resolve_codec
    ):
        mock_resolve_codec.return_value = "aac/16000"
        mock_stream_request.return_value = {"status": "success"}

        result = go2rtc_module.send_native_talkback(
            {"audio_url": "http://127.0.0.1:55000/api/talkback-file/test.wav"},
            "north-yard",
        )

        self.assertEqual(result, {"status": "success"})
        mock_stream_request.assert_called_once_with(
            "north-yard",
            "ffmpeg:http://127.0.0.1:55000/api/talkback-file/test.wav#audio=aac/16000#input=file",
            mode="url",
            timeout=20.0,
        )

    @patch.object(stream_manager_module, "preload_native_stream")
    @patch.object(stream_manager_module, "write_native_snapshot")
    def test_stream_manager_prefers_native_snapshot_for_selected_camera(
        self, mock_write_native_snapshot, mock_preload
    ):
        manager = StreamManager(DummyApi())
        manager.streams["north-yard"] = SimpleNamespace(
            get_info=lambda: {
                "native_selected": True,
                "native_api_reachable": True,
                "native_alias": "north-yard",
            }
        )
        mock_preload.return_value = {"ok": True}
        mock_write_native_snapshot.return_value = True

        result = manager.get_snapshot("north-yard")

        self.assertEqual(result, {"ok": True, "source": "go2rtc"})
        mock_preload.assert_called_once_with("north-yard")
        mock_write_native_snapshot.assert_called_once_with(
            "north-yard", "north-yard", warn_on_failure=True
        )

    @patch.object(stream_manager_module, "preload_native_stream")
    @patch.object(stream_manager_module, "write_native_snapshot")
    def test_stream_manager_uses_go2rtc_alias_snapshot_when_api_is_reachable(
        self, mock_write_native_snapshot, mock_preload
    ):
        manager = StreamManager(DummyApi())
        manager.streams["back-yard-sub"] = SimpleNamespace(
            get_info=lambda: {
                "native_selected": False,
                "native_api_reachable": True,
                "native_alias": "back-yard-sd",
            }
        )
        mock_preload.return_value = {"ok": True}
        mock_write_native_snapshot.return_value = True

        result = manager.get_snapshot("back-yard-sub")

        self.assertEqual(result, {"ok": True, "source": "go2rtc"})
        mock_preload.assert_called_once_with("back-yard-sd")
        mock_write_native_snapshot.assert_called_once_with(
            "back-yard-sd", "back-yard-sub", warn_on_failure=False
        )

    @patch.object(stream_manager_module, "preload_native_stream")
    @patch.object(stream_manager_module, "write_native_snapshot")
    def test_stream_manager_tries_sd_alias_for_registered_parent_stream(
        self, mock_write_native_snapshot, mock_preload
    ):
        manager = StreamManager(DummyApi())
        manager.streams["north-yard"] = SimpleNamespace(
            get_info=lambda: {
                "native_selected": False,
                "native_api_reachable": True,
                "native_alias": "north-yard",
            }
        )
        mock_preload.return_value = {"ok": True}
        mock_write_native_snapshot.side_effect = [False, True]

        result = manager.get_snapshot("north-yard")

        self.assertEqual(result, {"ok": True, "source": "go2rtc"})
        self.assertEqual(
            mock_write_native_snapshot.call_args_list,
            [
                call("north-yard", "north-yard", warn_on_failure=False),
                call("north-yard-sd", "north-yard", warn_on_failure=False),
            ],
        )

    @patch.object(stream_manager_module, "preload_native_stream")
    @patch.object(stream_manager_module, "write_native_snapshot")
    def test_stream_manager_repreloads_stale_native_alias_after_failed_snapshot(
        self, mock_write_native_snapshot, mock_preload
    ):
        manager = StreamManager(DummyApi())
        manager.native_preloads.add("north-yard")
        manager.streams["north-yard"] = SimpleNamespace(
            get_info=lambda: {
                "native_selected": True,
                "native_api_reachable": True,
                "native_alias": "north-yard",
            }
        )
        mock_preload.return_value = {"ok": True}
        mock_write_native_snapshot.side_effect = [False, True]

        result = manager.get_snapshot("north-yard")

        self.assertEqual(result, {"ok": True, "source": "go2rtc"})
        mock_preload.assert_called_once_with("north-yard")
        self.assertEqual(
            mock_write_native_snapshot.call_args_list,
            [
                call("north-yard", "north-yard", warn_on_failure=True),
                call("north-yard", "north-yard", warn_on_failure=True),
            ],
        )

    @patch.object(StreamManager, "get_snapshot")
    def test_refresh_preview_falls_back_to_cloud_thumbnail(self, mock_get_snapshot):
        api = DummyApi()
        api.save_thumbnail = Mock(return_value=True)
        manager = StreamManager(api)
        mock_get_snapshot.return_value = {"ok": False, "source": "rtsp"}

        result = manager.refresh_preview("hamster")

        self.assertEqual(result, {"ok": True, "source": "api"})
        api.save_thumbnail.assert_called_once_with("hamster", "")

    @patch.object(stream_manager_module, "publish_topic")
    @patch.object(StreamManager, "refresh_preview", return_value={"ok": True, "source": "go2rtc"})
    def test_send_cmd_update_snapshot_refreshes_native_only_camera(
        self, mock_refresh_preview, mock_publish_topic
    ):
        api = DummyApi()
        api.get_camera = Mock(return_value=SimpleNamespace(name_uri="north-yard"))
        manager = StreamManager(api)

        result = manager.send_cmd("north-yard", "update_snapshot")

        self.assertEqual(result["status"], "success")
        self.assertTrue(result["response"])
        mock_refresh_preview.assert_called_once_with("north-yard")
        mock_publish_topic.assert_called_once()

    @patch.object(stream_manager_module, "rtsp_snap_cmd", return_value=["ffmpeg", "-y", "unused.jpg"])
    def test_get_rtsp_snap_rejects_decode_errors_and_keeps_existing_preview(self, _mock_cmd):
        manager = StreamManager(DummyApi())
        stream = SimpleNamespace(start=Mock())
        manager.streams["garage-sub"] = stream

        with tempfile.TemporaryDirectory() as temp_dir:
            final_path = os.path.join(temp_dir, "garage-sub.jpg")
            with open(final_path, "wb") as handle:
                handle.write(b"existing-preview")

            fake_popen = FakeSnapshotPopen(
                ["ffmpeg", "-y", os.path.join(temp_dir, "garage-sub.jpg.tmp")],
                stderr_output=b"[h264 @ 0x1] error while decoding MB 47 19, bytestream -15\n",
            )

            with patch.object(stream_manager_module, "IMG_PATH", temp_dir + os.sep), patch.object(
                stream_manager_module, "Popen", return_value=fake_popen
            ):
                result = manager.get_rtsp_snap("garage-sub")

            self.assertFalse(result)
            with open(final_path, "rb") as handle:
                self.assertEqual(handle.read(), b"existing-preview")

        stream.start.assert_called_once_with()

    @patch.object(stream_manager_module, "rtsp_snap_cmd", return_value=["ffmpeg", "-y", "unused.jpg"])
    def test_get_rtsp_snap_replaces_preview_without_decode_errors(self, _mock_cmd):
        manager = StreamManager(DummyApi())
        stream = SimpleNamespace(start=Mock())
        manager.streams["deck-sub"] = stream
        fresh_preview = valid_jpeg_bytes((180, 48, 48))

        with tempfile.TemporaryDirectory() as temp_dir:
            final_path = os.path.join(temp_dir, "deck-sub.jpg")
            fake_popen = FakeSnapshotPopen(
                ["ffmpeg", "-y", os.path.join(temp_dir, "deck-sub.jpg.tmp")],
                stderr_output=b"",
                image_bytes=fresh_preview,
            )

            with patch.object(stream_manager_module, "IMG_PATH", temp_dir + os.sep), patch.object(
                stream_manager_module, "Popen", return_value=fake_popen
            ):
                result = manager.get_rtsp_snap("deck-sub")

            self.assertTrue(result)
            with open(final_path, "rb") as handle:
                self.assertEqual(handle.read(), fresh_preview)
            registry_path = os.path.join(temp_dir, ".snapshot_hashes.json")
            with open(registry_path, "r", encoding="utf-8") as handle:
                self.assertIn("deck-sub", handle.read())

    @patch.object(stream_manager_module, "rtsp_snap_cmd", return_value=["ffmpeg", "-y", "unused.jpg"])
    def test_get_rtsp_snap_rejects_unchanged_preview_as_stale(self, _mock_cmd):
        manager = StreamManager(DummyApi())
        stream = SimpleNamespace(start=Mock())
        manager.streams["deck-sub"] = stream
        stale_preview = valid_jpeg_bytes((72, 96, 168))

        with tempfile.TemporaryDirectory() as temp_dir:
            final_path = os.path.join(temp_dir, "deck-sub.jpg")
            with open(final_path, "wb") as handle:
                handle.write(stale_preview)

            fake_popen = FakeSnapshotPopen(
                ["ffmpeg", "-y", os.path.join(temp_dir, "deck-sub.jpg.tmp")],
                stderr_output=b"",
                image_bytes=stale_preview,
            )

            with patch.object(stream_manager_module, "IMG_PATH", temp_dir + os.sep), patch.object(
                stream_manager_module, "Popen", return_value=fake_popen
            ):
                result = manager.get_rtsp_snap("deck-sub")

            self.assertFalse(result)
            with open(final_path, "rb") as handle:
                self.assertEqual(handle.read(), stale_preview)

    def test_get_rtsp_snap_retries_without_frame_skip_after_timeout(self):
        manager = StreamManager(DummyApi())
        stream = SimpleNamespace(start=Mock())
        manager.streams["garage-sub"] = stream
        fallback_preview = valid_jpeg_bytes((120, 84, 44))

        def snap_cmd(cam_name, interval=False, skip_early_frames=True):
            cmd = ["ffmpeg"]
            if skip_early_frames:
                cmd += ["-vf", r"select=gte(n\,15)"]
            return cmd + ["unused.jpg"]

        created = []

        def fake_popen(cmd, stdout=None, stderr=None):
            created.append(cmd)
            if len(created) == 1:
                return FakeTimeoutPopen(cmd, stdout=stdout, stderr=stderr)
            return FakeSnapshotPopen(
                cmd,
                stdout=stdout,
                stderr=stderr,
                image_bytes=fallback_preview,
            )

        with tempfile.TemporaryDirectory() as temp_dir:
            final_path = os.path.join(temp_dir, "garage-sub.jpg")
            with patch.object(stream_manager_module, "IMG_PATH", temp_dir + os.sep), patch.object(
                stream_manager_module, "rtsp_snap_cmd", side_effect=snap_cmd
            ) as mock_cmd, patch.object(stream_manager_module, "Popen", side_effect=fake_popen):
                result = manager.get_rtsp_snap("garage-sub")

            self.assertTrue(result)
            with open(final_path, "rb") as handle:
                self.assertEqual(handle.read(), fallback_preview)

        self.assertEqual(
            mock_cmd.call_args_list,
            [
                call("garage-sub", skip_early_frames=True),
                call("garage-sub", skip_early_frames=False),
            ],
        )
        self.assertIn("-vf", created[0])
        self.assertNotIn("-vf", created[1])

    def test_write_native_snapshot_rejects_unchanged_preview_as_stale(self):
        stale_preview = valid_jpeg_bytes((32, 110, 180))
        response = Mock(status_code=200, content=stale_preview)
        response.raise_for_status = Mock()

        with tempfile.TemporaryDirectory() as temp_dir:
            final_path = pathlib.Path(temp_dir) / "deck-sub.jpg"
            final_path.write_bytes(stale_preview)

            with patch.object(go2rtc_module, "IMG_PATH", temp_dir + os.sep), patch.object(
                go2rtc_module.requests, "get", return_value=response
            ), patch.object(go2rtc_module.time, "sleep"):
                result = go2rtc_module.write_native_snapshot("deck-sd", "deck-sub", timeout=0.01)

            self.assertFalse(result)
            self.assertEqual(final_path.read_bytes(), stale_preview)

    def test_write_native_snapshot_waits_for_new_frame_before_failing(self):
        stale_preview = valid_jpeg_bytes((60, 80, 180))
        fresh_preview = valid_jpeg_bytes((180, 120, 40))
        stale_response = Mock(status_code=200, content=stale_preview)
        stale_response.raise_for_status = Mock()
        fresh_response = Mock(status_code=200, content=fresh_preview)
        fresh_response.raise_for_status = Mock()

        with tempfile.TemporaryDirectory() as temp_dir:
            final_path = pathlib.Path(temp_dir) / "north-yard.jpg"
            final_path.write_bytes(stale_preview)

            with patch.object(go2rtc_module, "IMG_PATH", temp_dir + os.sep), patch.object(
                go2rtc_module.requests, "get", side_effect=[stale_response, fresh_response]
            ), patch.object(go2rtc_module.time, "sleep"):
                result = go2rtc_module.write_native_snapshot("north-yard", "north-yard", timeout=1.0)

            self.assertTrue(result)
            self.assertEqual(final_path.read_bytes(), fresh_preview)
            self.assertTrue((pathlib.Path(temp_dir) / ".snapshot_hashes.json").exists())

    def test_write_native_snapshot_rejects_empty_response(self):
        response = Mock(status_code=200, content=b"")
        response.raise_for_status = Mock()

        with tempfile.TemporaryDirectory() as temp_dir:
            with patch.object(go2rtc_module, "IMG_PATH", temp_dir + os.sep), patch.object(
                go2rtc_module.requests, "get", return_value=response
            ), patch.object(go2rtc_module.time, "sleep"):
                result = go2rtc_module.write_native_snapshot("garage-sd", "garage", timeout=0.01)

            self.assertFalse(result)
            self.assertFalse((pathlib.Path(temp_dir) / "garage.jpg").exists())

    def test_write_native_snapshot_timeout_fallback_is_not_warning(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            with patch.object(go2rtc_module, "IMG_PATH", temp_dir + os.sep), patch.object(
                go2rtc_module.requests, "get", side_effect=Exception("native read timed out")
            ), patch.object(go2rtc_module.time, "sleep"), patch.object(
                go2rtc_module.logger, "warning"
            ) as warning, patch.object(go2rtc_module.logger, "debug") as debug:
                result = go2rtc_module.write_native_snapshot("back-yard-sd", "back-yard-sub", timeout=0.01)

            self.assertFalse(result)
            warning.assert_not_called()
            debug.assert_called()
            self.assertFalse((pathlib.Path(temp_dir) / "back-yard-sub.jpg").exists())

    def test_write_native_snapshot_falls_back_fast_on_503(self):
        response = Mock(status_code=503, content=b"")
        response.raise_for_status = Mock()

        with tempfile.TemporaryDirectory() as temp_dir:
            with patch.object(go2rtc_module, "IMG_PATH", temp_dir + os.sep), patch.object(
                go2rtc_module.requests, "get", return_value=response
            ) as get, patch.object(go2rtc_module.time, "sleep") as sleep:
                result = go2rtc_module.write_native_snapshot("garage-sd", "garage")

            self.assertFalse(result)
            get.assert_called_once()
            sleep.assert_not_called()
            self.assertFalse((pathlib.Path(temp_dir) / "garage.jpg").exists())

    def test_write_native_snapshot_optional_404_is_not_warning(self):
        response = Mock(status_code=404, content=b"")
        response.raise_for_status = Mock()

        with tempfile.TemporaryDirectory() as temp_dir:
            with patch.object(go2rtc_module, "IMG_PATH", temp_dir + os.sep), patch.object(
                go2rtc_module.requests, "get", return_value=response
            ), patch.object(go2rtc_module.logger, "warning") as warning, patch.object(
                go2rtc_module.logger, "debug"
            ) as debug:
                result = go2rtc_module.write_native_snapshot(
                    "south-yard", "south-yard", warn_on_failure=False
                )

            self.assertFalse(result)
            warning.assert_not_called()
            debug.assert_called()
            self.assertFalse((pathlib.Path(temp_dir) / "south-yard.jpg").exists())

    def test_write_native_snapshot_rejects_non_image_response(self):
        response = Mock(status_code=200, content=b"<!doctype html><html>redirect</html>")
        response.raise_for_status = Mock()

        with tempfile.TemporaryDirectory() as temp_dir:
            with patch.object(go2rtc_module, "IMG_PATH", temp_dir + os.sep), patch.object(
                go2rtc_module.requests, "get", return_value=response
            ):
                result = go2rtc_module.write_native_snapshot("garage-sd", "garage")

            self.assertFalse(result)
            self.assertFalse((pathlib.Path(temp_dir) / "garage.jpg").exists())

    @patch.object(stream_manager_module, "write_native_snapshot", return_value=True)
    def test_get_snapshot_uses_native_alias_without_registered_stream(self, mock_write_native_snapshot):
        manager = StreamManager(DummyApi())

        result = manager.get_snapshot("north-yard")

        self.assertEqual(result, {"ok": True, "source": "go2rtc"})
        mock_write_native_snapshot.assert_called_once_with(
            "north-yard", "north-yard", warn_on_failure=False
        )

    @patch.object(stream_manager_module, "write_native_snapshot")
    def test_get_snapshot_tries_sd_alias_without_registered_parent_stream(self, mock_write_native_snapshot):
        manager = StreamManager(DummyApi())
        mock_write_native_snapshot.side_effect = [False, True]

        result = manager.get_snapshot("south-yard")

        self.assertEqual(result, {"ok": True, "source": "go2rtc"})
        self.assertEqual(
            mock_write_native_snapshot.call_args_list,
            [
                call("south-yard", "south-yard", warn_on_failure=False),
                call("south-yard-sd", "south-yard", warn_on_failure=False),
            ],
        )

    def test_rtsp_snapshot_command_skips_early_frames(self):
        cmd = ffmpeg_module.rtsp_snap_cmd("south-yard-sub")

        self.assertIn("-vf", cmd)
        vf_index = cmd.index("-vf")
        self.assertIn(r"select=gte(n\,15)", cmd[vf_index + 1])

    @patch.object(go2rtc_module, "_resolve_talkback_ffmpeg_codec")
    @patch.object(go2rtc_module, "_go2rtc_stream_request")
    @patch.object(go2rtc_module, "_cleanup_stale_talkback_files")
    @patch.object(go2rtc_module, "_talkback_temp_dir")
    def test_send_native_talkback_audio_b64_writes_temp_file_and_calls_stream_request(
        self, mock_temp_dir, mock_cleanup, mock_stream_request, mock_resolve_codec
    ):
        import base64
        import tempfile
        from pathlib import Path

        mock_resolve_codec.return_value = "aac/16000"
        mock_stream_request.return_value = {"status": "success"}

        # Use a real temp dir so NamedTemporaryFile can actually create the file
        with tempfile.TemporaryDirectory() as real_tmp:
            mock_temp_dir.return_value = Path(real_tmp)

            audio_bytes = b"RIFF\x00\x00\x00\x00WAVEfmt "
            audio_b64 = base64.b64encode(audio_bytes).decode()

            result = go2rtc_module.send_native_talkback(
                {"audio_b64": audio_b64, "file_ext": "wav"},
                "north-yard",
            )

        self.assertEqual(result, {"status": "success"})
        mock_resolve_codec.assert_called_once()
        mock_cleanup.assert_called_once()
        call_args = mock_stream_request.call_args
        self.assertEqual(call_args[0][0], "north-yard")
        self.assertIn("aac/16000", call_args[0][1])
        self.assertIn("#input=file", call_args[0][1])
        self.assertEqual(call_args[1]["mode"], "file")

    def test_send_native_talkback_rejects_both_audio_b64_and_audio_url(self):
        import base64

        audio_b64 = base64.b64encode(b"fake audio").decode()
        result = go2rtc_module.send_native_talkback(
            {"audio_b64": audio_b64, "audio_url": "http://example.com/audio.wav"},
            "north-yard",
        )

        self.assertEqual(result["status"], "error")
        self.assertIn("audio_b64", result["response"])
        self.assertIn("audio_url", result["response"])

    @patch.object(bridge_diagnostics_module, "go2rtc_probe")
    def test_collect_bridge_diagnostics_includes_go2rtc_selection(self, mock_probe):
        mock_probe.return_value = {
            "api": {"reachable": True},
            "aliases": ["north-yard", "north-yard-sd"],
        }

        details = collect_bridge_diagnostics(
            "north-yard",
            {
                "native_supported": True,
                "native_selected": True,
                "native_reason": "HL_CAM4 validated on native go2rtc",
                "native_preload": True,
                "snapshot_source": "go2rtc",
                "native_alias": "north-yard",
                "talkback_supported": True,
                "talkback_reason": "API-first talkback is available through the native go2rtc alias",
                "talkback_source": "go2rtc",
                "talkback_alias": "north-yard",
            },
        )

        self.assertTrue(details["go2rtc"]["selection"]["selected"])
        self.assertTrue(details["go2rtc"]["selection"]["talkback_supported"])
        self.assertEqual(details["go2rtc"]["alias"], {"name": "north-yard", "exists": True})
        self.assertEqual(
            details["go2rtc"]["talkback_alias"], {"name": "north-yard", "exists": True}
        )


if __name__ == "__main__":
    unittest.main()

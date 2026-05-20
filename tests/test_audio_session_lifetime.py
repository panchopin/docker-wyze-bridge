#!/usr/bin/env python3

import pathlib
import sys
import unittest
from ctypes import c_int
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "app"))

if not hasattr(sys.modules.get("wyzebridge.wyze_stream"), "StreamStatus"):
    for module_name in list(sys.modules):
        if module_name == "wyzebridge" or module_name.startswith("wyzebridge."):
            del sys.modules[module_name]

import wyzebridge.wyze_stream as wyze_stream_module
from wyzebridge.wyze_stream import (
    QueueTuple,
    StreamStatus,
    StreamTuple,
    start_tutk_stream,
)


class FakeSession:
    def __init__(self):
        self.closed = False
        self.enable_audio = False
        self.read_while_open = False

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        self.closed = True

    def recv_bridge_data(self):
        if self.closed:
            raise AssertionError("session closed before bridge read")
        self.read_while_open = True
        yield (b"frame", None)


class FakeIOTC:
    def __init__(self, session):
        self._session = session

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def session(self, *_args, **_kwargs):
        return self._session


class FakePopen:
    def __init__(self, *_args, **_kwargs):
        self.stdin = self
        self.writes = []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def write(self, data):
        self.writes.append(data)


class TestAudioSessionLifetime(unittest.TestCase):
    def test_stream_reads_frames_before_session_context_exits(self):
        fake_session = FakeSession()
        stream = StreamTuple(
            user=SimpleNamespace(),
            camera=SimpleNamespace(
                is_vertical=False,
                product_model="WYZE_CAKP2JFUS",
                model_name="V3",
                mac="001122334455",
                ip="192.168.1.144",
                p2p_id="P2P-ID",
                dtls=1,
                parent_dtls=0,
                enr="ENR",
                is_2k=False,
                is_floodlight=False,
            ),
            options=SimpleNamespace(substream=False),
        )
        state = c_int(StreamStatus.CONNECTING)

        with (
            patch.object(wyze_stream_module, "WyzeIOTC", return_value=FakeIOTC(fake_session)),
            patch.object(wyze_stream_module, "get_cam_params", return_value=("h264", {})),
            patch.object(wyze_stream_module, "setup_control", return_value=None),
            patch.object(wyze_stream_module, "get_ffmpeg_cmd", return_value=["ffmpeg"]),
            patch.object(wyze_stream_module, "Popen", FakePopen),
        ):
            start_tutk_stream("garage", stream, QueueTuple(None, None), state)

        self.assertTrue(
            fake_session.read_while_open,
            "session should remain open while bridge frames are read",
        )


if __name__ == "__main__":
    unittest.main()

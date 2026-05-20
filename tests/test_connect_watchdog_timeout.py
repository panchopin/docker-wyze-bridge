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
from wyzebridge.wyze_stream import StreamStatus, WyzeStream


class TestConnectWatchdogTimeout(unittest.TestCase):
    def test_connecting_watchdog_respects_retry_window(self):
        stream = WyzeStream.__new__(WyzeStream)
        stream.camera = SimpleNamespace(
            nickname="North Yard",
            is_battery=False,
            product_model="WYZEC1",
            is_kvs=False,
            can_substream=False,
        )
        stream.options = SimpleNamespace(reconnect=False, substream=False)
        stream.start_time = 100.0
        stream.stop = lambda: setattr(stream, "stopped", True)
        stream.stopped = False
        stream._state = c_int(StreamStatus.CONNECTING)

        with patch.object(wyze_stream_module, "time", return_value=126.0):
            state = WyzeStream.health_check(stream, should_start=False)

        self.assertEqual(state, StreamStatus.CONNECTING)
        self.assertFalse(stream.stopped)


if __name__ == "__main__":
    unittest.main()

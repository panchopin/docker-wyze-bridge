#!/usr/bin/env python3

import pathlib
import sys
import unittest
from unittest.mock import patch

sys.path.insert(
    0, str(pathlib.Path(__file__).resolve().parent.parent / ".ha_live_addon" / "app")
)

from wyzebridge.ffmpeg import get_ffmpeg_cmd, internal_rtsp_url


class TestFfmpegInternalRtspUrl(unittest.TestCase):
    def test_internal_rtsp_url_defaults_to_8554(self):
        with patch.dict("os.environ", {}, clear=False):
            self.assertEqual(internal_rtsp_url("north-yard-sub"), "rtsp://127.0.0.1:8554/north-yard-sub")

    def test_internal_rtsp_url_uses_mtx_rtspaddress_port(self):
        with patch.dict("os.environ", {"MTX_RTSPADDRESS": ":58554"}, clear=False):
            self.assertEqual(internal_rtsp_url("north-yard-sub"), "rtsp://127.0.0.1:58554/north-yard-sub")

    def test_get_ffmpeg_cmd_publishes_to_configured_internal_rtsp_port(self):
        with patch.dict("os.environ", {"MTX_RTSPADDRESS": ":58554"}, clear=False):
            cmd = get_ffmpeg_cmd("north-yard-sub", "h264", {}, False)

        self.assertIn("rtsp://127.0.0.1:58554/north-yard-sub", cmd[-1])


if __name__ == "__main__":
    unittest.main()

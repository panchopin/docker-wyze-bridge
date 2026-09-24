#!/usr/bin/env python3
"""Tests for the recorded-audio-loss watchdog and the fMP4 probe behind it."""

import os
import pathlib
import struct
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "app"))

from wyzebridge.av_watchdog import (  # noqa: E402
    AvSyncWatchdog,
    newest_finished_segment,
    parse_duration,
)
import wyzebridge.mtx_server as mtx_server_module  # noqa: E402  (loads real PyYAML early)
from wyzebridge.fmp4_probe import track_durations  # noqa: E402

VIDEO_TRACK = 1
AUDIO_TRACK = 2
VIDEO_TIMESCALE = 90000
AUDIO_TIMESCALE = 16000


def _box(btype: bytes, payload: bytes) -> bytes:
    return struct.pack(">I4s", 8 + len(payload), btype) + payload


def _tkhd(track_id: int) -> bytes:
    # version/flags, creation, modification, track_ID, reserved, duration
    return _box(b"tkhd", struct.pack(">IIIIII", 0, 0, 0, track_id, 0, 0))


def _mdhd(timescale: int) -> bytes:
    # version/flags, creation, modification, timescale, duration, lang+pre
    return _box(b"mdhd", struct.pack(">IIIIII", 0, 0, 0, timescale, 0, 0))


def _hdlr(handler: bytes) -> bytes:
    return _box(b"hdlr", struct.pack(">II4s", 0, 0, handler) + b"\x00" * 12)


def _trak(track_id: int, timescale: int, handler: bytes) -> bytes:
    return _box(b"trak", _tkhd(track_id) + _box(b"mdia", _mdhd(timescale) + _hdlr(handler)))


def _moof(track_id: int, durations: list[int], with_durations: bool = True) -> bytes:
    tfhd = _box(b"tfhd", struct.pack(">II", 0x020000, track_id))
    if with_durations:
        # flags 0x000701: data-offset + per-sample duration, size and flags
        payload = struct.pack(">III", 0x000701, len(durations), 0)
        for duration in durations:
            payload += struct.pack(">III", duration, 100, 0)
    else:
        # flags 0x000601: no per-sample duration; the reader must fall back to
        # a traf/trex default, and MediaMTX leaves those at zero.
        payload = struct.pack(">III", 0x000601, len(durations), 0)
        for _ in durations:
            payload += struct.pack(">II", 100, 0)
    trun = _box(b"trun", payload)
    mfhd = _box(b"mfhd", struct.pack(">II", 0, 1))
    return _box(b"moof", mfhd + _box(b"traf", tfhd + trun))


def write_fmp4(
    path: pathlib.Path,
    video_samples: int,
    audio_samples: int,
    video_sample_ticks: int = 4500,  # 20fps at 90kHz
    audio_sample_ticks: int = 1024,  # AAC frame at 16kHz
    declare_audio: bool = True,
) -> pathlib.Path:
    """Write a fragmented MP4 shaped like the ones MediaMTX records."""
    traks = _trak(VIDEO_TRACK, VIDEO_TIMESCALE, b"vide")
    if declare_audio:
        traks += _trak(AUDIO_TRACK, AUDIO_TIMESCALE, b"soun")

    out = _box(b"ftyp", b"iso5" + b"\x00" * 8)
    out += _box(b"moov", _box(b"mvhd", b"\x00" * 100) + traks)

    # Interleave fragments the way the recorder does, video part then audio.
    for index in range(max(video_samples, audio_samples)):
        if index < video_samples:
            out += _moof(VIDEO_TRACK, [video_sample_ticks])
            out += _box(b"mdat", b"\x00" * 16)
        if index < audio_samples:
            out += _moof(AUDIO_TRACK, [audio_sample_ticks])
            out += _box(b"mdat", b"\x00" * 16)

    path.write_bytes(out)
    return path


class TestParseDuration(unittest.TestCase):
    def test_go_duration_strings(self):
        self.assertEqual(parse_duration("60s", 1.0), 60.0)
        self.assertEqual(parse_duration("1m", 1.0), 60.0)
        self.assertEqual(parse_duration("1m30s", 1.0), 90.0)
        self.assertEqual(parse_duration("500ms", 1.0), 0.5)

    def test_falls_back_when_unparseable(self):
        self.assertEqual(parse_duration("", 60.0), 60.0)
        self.assertEqual(parse_duration("nonsense", 60.0), 60.0)
        self.assertEqual(parse_duration(None, 60.0), 60.0)


class TestFmp4Probe(unittest.TestCase):
    def setUp(self):
        self._dir = tempfile.TemporaryDirectory()
        self.tmp = pathlib.Path(self._dir.name)
        self.addCleanup(self._dir.cleanup)

    def test_measures_both_tracks(self):
        clip = write_fmp4(self.tmp / "full.mp4", video_samples=1200, audio_samples=938)
        measured = track_durations(clip)
        self.assertTrue(measured.ok)
        self.assertAlmostEqual(measured.video, 60.0, places=3)
        self.assertAlmostEqual(measured.audio, 938 * 1024 / 16000, places=3)
        self.assertEqual(measured.audio_deficit, 0.0)

    def test_declared_but_empty_audio_reads_as_total_loss(self):
        """The case ffprobe gets wrong: a declared audio track with no samples.

        `stream=duration` reports the movie duration for it and the stream
        looks full-length, so the deficit must come from sample counts.
        """
        clip = write_fmp4(self.tmp / "silent.mp4", video_samples=1200, audio_samples=0)
        measured = track_durations(clip)
        self.assertTrue(measured.ok)
        self.assertAlmostEqual(measured.video, 60.0, places=3)
        self.assertEqual(measured.audio, 0.0)
        self.assertAlmostEqual(measured.audio_deficit, 60.0, places=3)

    def test_partial_audio_loss(self):
        clip = write_fmp4(self.tmp / "partial.mp4", video_samples=1200, audio_samples=340)
        measured = track_durations(clip)
        self.assertAlmostEqual(measured.audio, 21.76, places=2)
        self.assertAlmostEqual(measured.audio_deficit, 38.24, places=2)

    def test_no_audio_track_is_not_a_deficit(self):
        clip = write_fmp4(
            self.tmp / "video_only.mp4",
            video_samples=1200,
            audio_samples=0,
            declare_audio=False,
        )
        measured = track_durations(clip)
        self.assertIsNone(measured.audio)
        self.assertIsNone(measured.audio_deficit)

    def test_unreadable_files_report_no_measurement(self):
        missing = track_durations(self.tmp / "nope.mp4")
        self.assertFalse(missing.ok)
        self.assertIsNone(missing.audio_deficit)

        junk = self.tmp / "junk.ts"
        junk.write_bytes(b"\x47" * 4096)
        self.assertFalse(track_durations(junk).ok)

    def test_unmeasurable_fragment_is_not_reported_as_loss(self):
        """A trun without per-sample durations and no default measures zero.

        Reading that as "the track got nothing" would trigger a needless
        rebuild, so it has to come back as no measurement at all.
        """
        traks = _trak(VIDEO_TRACK, VIDEO_TIMESCALE, b"vide") + _trak(
            AUDIO_TRACK, AUDIO_TIMESCALE, b"soun"
        )
        out = _box(b"ftyp", b"iso5" + b"\x00" * 8)
        out += _box(b"moov", _box(b"mvhd", b"\x00" * 100) + traks)
        out += _moof(VIDEO_TRACK, [4500], with_durations=False)
        out += _box(b"mdat", b"\x00" * 16)
        clip = self.tmp / "nodurations.mp4"
        clip.write_bytes(out)

        measured = track_durations(clip)

        self.assertFalse(measured.ok)
        self.assertIsNone(measured.audio_deficit)

    def test_truncated_file_is_not_reported_as_loss(self):
        clip = write_fmp4(self.tmp / "cut.mp4", video_samples=1200, audio_samples=1200)
        data = clip.read_bytes()
        clip.write_bytes(data[: len(data) // 2] + b"\x00\x00\x00\x40trun")
        self.assertFalse(track_durations(clip).ok)


class TestRecordRoot(unittest.TestCase):
    def test_result_is_cached(self):
        """ensure_record_path() logs on every call and the watchdog asks each
        cycle, so the answer must be computed once per camera."""
        mtx_server_module.record_root.cache_clear()
        with patch.object(
            mtx_server_module,
            "ensure_record_path",
            wraps=mtx_server_module.ensure_record_path,
        ) as spy:
            first = mtx_server_module.record_root("cache-probe")
            second = mtx_server_module.record_root("cache-probe")
        self.assertEqual(first, second)
        self.assertEqual(spy.call_count, 1)


class TestNewestFinishedSegment(unittest.TestCase):
    def setUp(self):
        self._dir = tempfile.TemporaryDirectory()
        self.tmp = pathlib.Path(self._dir.name)
        self.addCleanup(self._dir.cleanup)

    def _touch(self, rel: str, age_seconds: float) -> pathlib.Path:
        path = self.tmp / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"x")
        stamp = time.time() - age_seconds
        os.utime(path, (stamp, stamp))
        return path

    def test_skips_the_segment_still_being_written(self):
        self._touch("2026-09/23/09/old.mp4", age_seconds=300)
        finished = self._touch("2026-09/23/09/done.mp4", age_seconds=120)
        self._touch("2026-09/23/09/inprogress.mp4", age_seconds=1)
        found = newest_finished_segment(self.tmp, time.time())
        self.assertEqual(found, finished)

    def test_falls_back_to_previous_directory_at_an_hour_boundary(self):
        finished = self._touch("2026-09/23/09/done.mp4", age_seconds=200)
        self._touch("2026-09/23/10/inprogress.mp4", age_seconds=1)
        found = newest_finished_segment(self.tmp, time.time())
        self.assertEqual(found, finished)

    def test_missing_root_is_tolerated(self):
        self.assertIsNone(newest_finished_segment(self.tmp / "absent", time.time()))


class FakeMtx:
    """Stands in for MtxServer: records which paths were rebuilt."""

    def __init__(self, paths, refuse=()):
        self._paths = paths
        self._refuse = set(refuse)
        self.resets = []

    def watched_record_paths(self):
        return dict(self._paths)

    def reset_path(self, uri):
        if uri in self._refuse:
            return False
        self.resets.append(uri)
        return True


class TestAvSyncWatchdog(unittest.TestCase):
    def setUp(self):
        self._dir = tempfile.TemporaryDirectory()
        self.tmp = pathlib.Path(self._dir.name)
        self.addCleanup(self._dir.cleanup)
        self.root = self.tmp / "cam"
        self.root.mkdir()

    def _segment(self, video_samples, audio_samples, age=120.0, name="seg.mp4"):
        clip = write_fmp4(self.root / name, video_samples, audio_samples)
        stamp = time.time() - age
        os.utime(clip, (stamp, stamp))
        return clip

    def _watchdog(self, mtx, **kwargs):
        options = dict(
            segment_seconds=60.0, threshold=1.0, interval=120.0, cooldown=300.0
        )
        options.update(kwargs)
        return AvSyncWatchdog(
            watched_paths=mtx.watched_record_paths,
            reset_path=mtx.reset_path,
            **options,
        )

    def test_rebuilds_the_path_when_audio_is_missing(self):
        self._segment(video_samples=1200, audio_samples=0)
        mtx = FakeMtx({"main-bedroom": self.root})
        watchdog = self._watchdog(mtx)

        deficits = watchdog.check_once()

        self.assertAlmostEqual(deficits["main-bedroom"], 60.0, places=1)
        self.assertEqual(mtx.resets, ["main-bedroom"])

    def test_video_loss_is_caught_too(self):
        """On the KVS route it is video that gets discarded, not audio.  The
        audio track then runs *longer*, so comparing the two against each
        other would read as healthy."""
        # 60s segment: ~1.7s of video missing, audio spilling past the end.
        self._segment(video_samples=1166, audio_samples=964)
        mtx = FakeMtx({"kitchen-cam": self.root})
        watchdog = self._watchdog(mtx)

        deficits = watchdog.check_once()

        self.assertAlmostEqual(deficits["kitchen-cam"], 1.7, places=1)
        self.assertEqual(mtx.resets, ["kitchen-cam"])
        self.assertEqual(
            watchdog.status()["paths"]["kitchen-cam"]["last_shortfall_track"], "video"
        )

    def test_audio_running_past_the_last_video_frame_is_not_loss(self):
        """Segments are cut on video, so a little audio beyond the final video
        frame is normal and must not trigger a rebuild."""
        # video exactly 60s, audio 1.7s longer
        self._segment(video_samples=1200, audio_samples=964)
        mtx = FakeMtx({"kitchen-cam": self.root})
        watchdog = self._watchdog(mtx)

        deficits = watchdog.check_once()

        self.assertEqual(deficits["kitchen-cam"], 0.0)
        self.assertEqual(mtx.resets, [])

    def test_a_whole_segment_is_judged_by_its_longest_track(self):
        """Heavy video loss must not be written off as a fragment: if video is
        the short track, using it as the yardstick hides exactly the case we
        are looking for."""
        # audio full length, video down to 15s
        self._segment(video_samples=300, audio_samples=938)
        mtx = FakeMtx({"kitchen-cam": self.root})
        watchdog = self._watchdog(mtx)

        deficits = watchdog.check_once()

        self.assertAlmostEqual(deficits["kitchen-cam"], 45.0, places=0)
        self.assertEqual(mtx.resets, ["kitchen-cam"])

    def test_healthy_recording_is_left_alone(self):
        self._segment(video_samples=1200, audio_samples=938)
        mtx = FakeMtx({"main-bedroom": self.root})
        watchdog = self._watchdog(mtx)

        watchdog.check_once()

        self.assertEqual(mtx.resets, [])

    def test_respects_the_cooldown(self):
        self._segment(video_samples=1200, audio_samples=0)
        mtx = FakeMtx({"main-bedroom": self.root})
        watchdog = self._watchdog(mtx)

        start = time.time()
        watchdog.check_once(now=start)
        # A later segment, still broken, but inside the cooldown window.
        self._segment(video_samples=1200, audio_samples=0, age=0.0, name="seg2.mp4")
        watchdog.check_once(now=start + 60)

        self.assertEqual(mtx.resets, ["main-bedroom"])

    def test_backoff_widens_after_repeated_failures(self):
        mtx = FakeMtx({"main-bedroom": self.root})
        watchdog = self._watchdog(mtx)
        start = time.time()

        # Cooldown is 300s and doubles after every rebuild, so the next one is
        # allowed at +600, then +1200 after that.
        for index, offset in enumerate((0, 600, 1800)):
            moment = start + offset
            clip = write_fmp4(self.root / f"s{index}.mp4", 1200, 0)
            os.utime(clip, (moment - 100, moment - 100))
            watchdog.check_once(now=moment)

        self.assertEqual(len(mtx.resets), 3)
        self.assertEqual(watchdog.status()["paths"]["main-bedroom"]["backoff"], 8)

    def test_backoff_holds_off_a_too_early_retry(self):
        mtx = FakeMtx({"main-bedroom": self.root})
        watchdog = self._watchdog(mtx)
        start = time.time()

        for index, offset in enumerate((0, 400)):
            moment = start + offset
            clip = write_fmp4(self.root / f"s{index}.mp4", 1200, 0)
            os.utime(clip, (moment - 100, moment - 100))
            watchdog.check_once(now=moment)

        # 400s < the 600s the first rebuild earned.
        self.assertEqual(len(mtx.resets), 1)

    def test_ignores_recordings_made_before_the_last_rebuild(self):
        """A pre-rebuild file must not count as evidence the rebuild failed."""
        self._segment(video_samples=1200, audio_samples=0, age=120.0)
        mtx = FakeMtx({"main-bedroom": self.root})
        watchdog = self._watchdog(mtx, cooldown=0.0)

        start = time.time()
        watchdog.check_once(now=start)
        self.assertEqual(len(mtx.resets), 1)

        # No newer segment yet: the only file predates the rebuild.
        deficits = watchdog.check_once(now=start + 1)
        self.assertIsNone(deficits["main-bedroom"])
        self.assertEqual(len(mtx.resets), 1)

    def test_stale_recordings_do_not_trigger_a_rebuild(self):
        """A camera that stopped recording hours ago cannot be fixed by a
        rebuild, and must not be restarted on a loop."""
        self._segment(video_samples=1200, audio_samples=0, age=6 * 3600)
        mtx = FakeMtx({"main-bedroom": self.root})
        watchdog = self._watchdog(mtx)

        deficits = watchdog.check_once()

        self.assertIsNone(deficits["main-bedroom"])
        self.assertEqual(mtx.resets, [])

    def test_recent_recordings_still_trigger(self):
        """The staleness guard must not swallow a normal, current segment."""
        self._segment(video_samples=1200, audio_samples=0, age=90.0)
        mtx = FakeMtx({"main-bedroom": self.root})
        watchdog = self._watchdog(mtx)

        watchdog.check_once()

        self.assertEqual(mtx.resets, ["main-bedroom"])

    def test_implausible_video_duration_is_not_trusted(self):
        # 29 frames spanning a nominal 60s segment: a malformed clip seen in
        # the wild during churn.  Comparing its tracks proves nothing.
        self._segment(video_samples=29, audio_samples=0)
        mtx = FakeMtx({"main-bedroom": self.root})
        watchdog = self._watchdog(mtx)

        deficits = watchdog.check_once()

        self.assertIsNone(deficits["main-bedroom"])
        self.assertEqual(mtx.resets, [])

    def test_refused_rebuild_does_not_count_as_one(self):
        self._segment(video_samples=1200, audio_samples=0)
        mtx = FakeMtx({"kitchen-cam": self.root}, refuse={"kitchen-cam"})
        watchdog = self._watchdog(mtx)

        watchdog.check_once()

        self.assertEqual(mtx.resets, [])
        self.assertEqual(watchdog.status()["paths"]["kitchen-cam"]["resets"], 0)

    def test_survives_a_failing_path(self):
        mtx = FakeMtx({"gone": self.tmp / "does-not-exist"})
        watchdog = self._watchdog(mtx)
        self.assertIsNone(watchdog.check_once()["gone"])


class TestMtxServerReset(unittest.TestCase):
    """reset_path() must nudge a non-recording field, and only where it is safe."""

    def setUp(self):
        self._dir = tempfile.TemporaryDirectory()
        self.tmp = pathlib.Path(self._dir.name)
        self.addCleanup(self._dir.cleanup)
        self.config = self.tmp / "mediamtx.yml"
        # Other test modules import wyzebridge from a second source root, so
        # a dotted-string patch target can resolve to a different module object
        # than the one under test.  Bind to the imported object instead.
        self.mtx_server = mtx_server_module
        self._patch = patch.object(self.mtx_server, "MTX_CONFIG", str(self.config))
        self._patch.start()
        self.addCleanup(self._patch.stop)

    def _server(self, paths):
        mtx_server = self.mtx_server
        self.config.write_text("paths: {}\n")
        with mtx_server.MtxInterface() as mtx:
            mtx.set("paths", paths)
        server = mtx_server.MtxServer.__new__(mtx_server.MtxServer)
        return server, mtx_server

    def test_toggles_an_inert_field_to_force_a_rebuild(self):
        server, mtx_server = self._server(
            {"main-bedroom": {"source": "rtsp://127.0.0.1:19554/main-bedroom", "record": True}}
        )

        self.assertTrue(server.reset_path("main-bedroom"))
        with self.mtx_server.MtxInterface() as mtx:
            first = mtx.get("paths.main-bedroom.sourceOnDemandCloseAfter")
        self.assertEqual(first, self.mtx_server.PATH_NUDGE[0])

        # A second rebuild must produce a *different* value, or the config is
        # unchanged and MediaMTX will not reload anything.
        self.assertTrue(server.reset_path("main-bedroom"))
        with self.mtx_server.MtxInterface() as mtx:
            second = mtx.get("paths.main-bedroom.sourceOnDemandCloseAfter")
        self.assertEqual(second, self.mtx_server.PATH_NUDGE[1])
        self.assertNotEqual(first, second)

    def test_recording_settings_are_untouched(self):
        """The nudge must not be a recording field: those hot-reload in place
        instead of rebuilding the path."""
        server, mtx_server = self._server(
            {"main-bedroom": {"source": "rtsp://x/y", "record": True, "recordPath": "/keep/me"}}
        )
        server.reset_path("main-bedroom")
        with self.mtx_server.MtxInterface() as mtx:
            self.assertEqual(mtx.get("paths.main-bedroom.recordPath"), "/keep/me")
            self.assertIs(mtx.get("paths.main-bedroom.record"), True)
            self.assertEqual(mtx.get("paths.main-bedroom.source"), "rtsp://x/y")

    def test_kvs_paths_use_a_lever_that_is_inert_for_them(self):
        """A whep:// path never reads rtspTransport, so toggling it rebuilds
        the path and changes nothing else.  sourceOnDemandCloseAfter would not
        do here — these paths are on-demand, so it is live."""
        server, _ = self._server(
            {
                "kvs": {
                    "source": "whep://127.0.0.1:8080/whep/kvs",
                    "record": True,
                    "sourceOnDemand": True,
                }
            }
        )

        self.assertTrue(server.reset_path("kvs"))
        with self.mtx_server.MtxInterface() as mtx:
            first = mtx.get("paths.kvs.rtspTransport")
            self.assertIsNone(mtx.get("paths.kvs.sourceOnDemandCloseAfter"))
        self.assertEqual(first, self.mtx_server.PATH_NUDGE_TRANSPORT[0])

        self.assertTrue(server.reset_path("kvs"))
        with self.mtx_server.MtxInterface() as mtx:
            second = mtx.get("paths.kvs.rtspTransport")
        self.assertEqual(second, self.mtx_server.PATH_NUDGE_TRANSPORT[1])

    def test_refuses_on_demand_rtsp_paths(self):
        """Neither lever is safe there: rtspTransport is live for an rtsp://
        source, and sourceOnDemandCloseAfter is live for an on-demand path."""
        server, _ = self._server(
            {"odd": {"source": "rtsp://host/x", "record": True, "sourceOnDemand": True}}
        )
        self.assertFalse(server.reset_path("odd"))

    def test_refuses_paths_without_a_static_source(self):
        server, _ = self._server({"publisher-path": {}})
        self.assertFalse(server.reset_path("publisher-path"))

    def test_watched_paths_cover_both_camera_routes(self):
        """Both routes can end up with a track offset, so both are watched —
        but only where a rebuild is actually possible."""
        server, _ = self._server(
            {
                "native": {"source": "rtsp://127.0.0.1:19554/native", "record": True},
                "kvs": {
                    "source": "whep://127.0.0.1:8080/whep/kvs",
                    "record": True,
                    "sourceOnDemand": True,
                },
                "not-recording": {"source": "rtsp://127.0.0.1:19554/x"},
                "no-source": {"record": True},
                "unrepairable": {
                    "source": "rtsp://host/x",
                    "record": True,
                    "sourceOnDemand": True,
                },
            }
        )
        self.assertEqual(sorted(server.watched_record_paths()), ["kvs", "native"])

    def test_config_is_written_atomically(self):
        """A half-written config would be picked up by MediaMTX's file watcher."""
        self.config.write_text("paths: {}\n")
        seen = []
        real_replace = os.replace

        def spy(src, dst):
            seen.append((src, dst))
            return real_replace(src, dst)

        with patch.object(self.mtx_server.os, "replace", side_effect=spy):
            with self.mtx_server.MtxInterface() as mtx:
                mtx.set("paths.demo.source", "rtsp://host/demo")

        self.assertEqual(len(seen), 1)
        self.assertEqual(seen[0][1], self.config)
        # No temp files left behind.
        self.assertEqual([p.name for p in self.tmp.iterdir()], ["mediamtx.yml"])


if __name__ == "__main__":
    unittest.main()

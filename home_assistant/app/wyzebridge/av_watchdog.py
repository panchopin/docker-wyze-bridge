"""Detect and repair audio that the MediaMTX recorder is throwing away.

Background
----------
Cameras served by the go2rtc sidecar reach MediaMTX over RTSP.  go2rtc rebuilds
each track's timeline from the camera's frame timestamps, which carry only the
sub-second part of the clock (`tsWrapPeriod = 1000000` in go2rtc's
`pkg/tutk/frame.go`) and are anchored per track, independently, on that track's
first frame.  Whole seconds lost in a gap are unrecoverable, so the audio
timeline slips behind the video timeline by an arbitrary, persistent offset.

MediaMTX's fMP4 recorder then refuses every audio sample that falls before the
current segment's start (`sample of track N received too late, discarding`),
because fMP4 cannot express a negative baseTime.  Once the offset reaches the
segment length, *all* audio is discarded.

The offset is fixed for the life of one RTSP connection and is cleared only
when that connection is re-established.  So: measure the damage on finished
recordings, and when it appears, make MediaMTX rebuild the path.

Scope
-----
Only paths that record from an `rtsp://` source and are not `sourceOnDemand`
are watched — that is exactly the set of go2rtc-native paths this affects.
On-demand KVS paths are left alone: they show the symptom far more rarely and
the repair below is not safe for them.
"""

import re
import threading
import time
from pathlib import Path
from typing import Callable, Optional

from wyzebridge.fmp4_probe import track_durations
from wyzebridge.logging import logger

_DURATION_UNITS = {"ms": 0.001, "s": 1.0, "m": 60.0, "h": 3600.0}
_DURATION_PART = re.compile(r"(\d+(?:\.\d+)?)(ms|h|m|s)")


def parse_duration(value: str, default: float) -> float:
    """Parse a Go duration string ("60s", "1m", "1m30s") into seconds."""
    parts = _DURATION_PART.findall(str(value or "").strip().lower())
    if not parts:
        return default
    total = sum(float(amount) * _DURATION_UNITS[unit] for amount, unit in parts)
    return total or default

# How far the newest file's mtime must be in the past before we trust it to be
# a finished segment rather than the one still being written.
_COMPLETION_GRACE = 15.0

# How old the newest finished segment may be before we stop drawing
# conclusions from it.  If recording has stopped altogether the newest file
# only gets older, and rebuilding the path would not bring it back — a dead
# camera must not be restarted on a loop.
_STALE_AFTER_SEGMENTS = 4

# A measured video duration outside this band means the segment itself is
# malformed (we have seen churn produce a clip whose timestamps span 95s but
# holds 29 frames).  Comparing tracks in that file tells us nothing.
_VIDEO_PLAUSIBILITY = (0.5, 4.0)  # multipliers of the configured segment length

# Directory levels to descend when hunting for the newest segment.  The record
# path is time-templated (…/%Y-%m/%d/%H/…), so this bounds the walk instead of
# scanning a recording archive that may hold months of files.
_MAX_DEPTH = 6


class PathState:
    """Per-path bookkeeping: what we last measured and last did about it."""

    __slots__ = ("last_checked", "last_reset", "last_deficit", "resets", "backoff")

    def __init__(self) -> None:
        self.last_checked: float = 0.0
        self.last_reset: float = 0.0
        self.last_deficit: Optional[float] = None
        self.resets: int = 0
        self.backoff: int = 1

    def as_dict(self) -> dict:
        return {
            "last_checked": self.last_checked or None,
            "last_reset": self.last_reset or None,
            "last_audio_deficit_seconds": self.last_deficit,
            "resets": self.resets,
            "backoff": self.backoff,
        }


def newest_finished_segment(root: Path, now: float) -> Optional[Path]:
    """Newest recording under `root` that is no longer being written.

    Descends by directory mtime rather than by name so it does not depend on
    the record-path template being lexicographically ordered.
    """
    try:
        if not root.is_dir():
            return None
    except OSError:
        return None

    def newest_files(directory: Path, depth: int) -> Optional[Path]:
        try:
            entries = list(directory.iterdir())
        except OSError:
            return None

        files = []
        dirs = []
        for entry in entries:
            try:
                if entry.is_dir():
                    dirs.append(entry)
                elif entry.suffix == ".mp4":
                    files.append(entry)
            except OSError:
                continue

        best: Optional[Path] = None
        best_mtime = 0.0
        for candidate in files:
            try:
                mtime = candidate.stat().st_mtime
            except OSError:
                continue
            # Skip the segment still being written.
            if now - mtime < _COMPLETION_GRACE:
                continue
            if mtime > best_mtime:
                best, best_mtime = candidate, mtime
        if best is not None:
            return best

        if depth >= _MAX_DEPTH:
            return None

        # Try subdirectories, newest first, until one yields a finished file.
        def dir_mtime(d: Path) -> float:
            try:
                return d.stat().st_mtime
            except OSError:
                return 0.0

        for sub in sorted(dirs, key=dir_mtime, reverse=True)[:3]:
            found = newest_files(sub, depth + 1)
            if found is not None:
                return found
        return None

    return newest_files(root, 0)


class AvSyncWatchdog:
    """Measures recorded audio loss and repairs it by rebuilding the path."""

    def __init__(
        self,
        watched_paths: Callable[[], dict[str, Path]],
        reset_path: Callable[[str], bool],
        segment_seconds: float,
        threshold: float,
        interval: float,
        cooldown: float,
        max_backoff: int = 8,
    ) -> None:
        self._watched_paths = watched_paths
        self._reset_path = reset_path
        self._segment_seconds = segment_seconds
        self._threshold = threshold
        self._interval = interval
        self._cooldown = cooldown
        self._max_backoff = max_backoff
        self._state: dict[str, PathState] = {}
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()

    # --- lifecycle ------------------------------------------------------

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run, name="av_watchdog", daemon=True
        )
        self._thread.start()
        logger.info(
            "[AV] Audio-loss watchdog started "
            f"(every {self._interval:.0f}s, trigger at {self._threshold:.1f}s lost, "
            f"cooldown {self._cooldown:.0f}s)"
        )

    def stop(self) -> None:
        self._stop.set()

    def _run(self) -> None:
        # Nothing has been recorded yet at boot; wait one full segment so the
        # first measurement has a finished file to look at.
        if self._stop.wait(self._segment_seconds + _COMPLETION_GRACE):
            return
        while not self._stop.is_set():
            try:
                self.check_once()
            except Exception as ex:  # never let the watchdog kill its thread
                logger.warning(f"[AV] watchdog cycle failed: {ex}")
            if self._stop.wait(self._interval):
                return

    # --- the actual work ------------------------------------------------

    def check_once(self, now: Optional[float] = None) -> dict[str, Optional[float]]:
        """One measurement pass.  Returns the deficit measured per path."""
        now = time.time() if now is None else now
        results: dict[str, Optional[float]] = {}

        for uri, root in self._watched_paths().items():
            state = self._state.setdefault(uri, PathState())
            deficit = self._measure(uri, root, state, now)
            results[uri] = deficit
            state.last_checked = now
            state.last_deficit = deficit

            if deficit is None or deficit <= self._threshold:
                if deficit is not None:
                    # A healthy reading means the last repair worked.
                    state.backoff = 1
                continue

            if not self._may_reset(state, now):
                continue

            logger.warning(
                f"[AV] {uri}: {deficit:.1f}s of audio missing from the last "
                f"{self._segment_seconds:.0f}s segment - rebuilding the path to "
                "resynchronise the RTSP source"
            )
            if self._reset_path(uri):
                state.last_reset = now
                state.resets += 1
                state.backoff = min(state.backoff * 2, self._max_backoff)
            else:
                logger.warning(f"[AV] {uri}: path rebuild refused, leaving it alone")

        return results

    def _may_reset(self, state: PathState, now: float) -> bool:
        if not state.last_reset:
            return True
        return (now - state.last_reset) >= self._cooldown * state.backoff

    def _measure(
        self, uri: str, root: Path, state: PathState, now: float
    ) -> Optional[float]:
        segment = newest_finished_segment(root, now)
        if segment is None:
            return None

        try:
            mtime = segment.stat().st_mtime
        except OSError:
            return None

        # Never judge a repair by a file recorded before it happened.
        if state.last_reset and mtime < state.last_reset:
            return None

        stale_after = self._segment_seconds * _STALE_AFTER_SEGMENTS + self._interval
        if now - mtime > stale_after:
            logger.debug(
                f"[AV] {uri}: newest finished segment is "
                f"{(now - mtime) / 60:.0f} min old, not recording - skipping"
            )
            return None

        measured = track_durations(segment)
        if not measured.ok or measured.video is None:
            return None

        low, high = _VIDEO_PLAUSIBILITY
        if not (
            self._segment_seconds * low
            <= measured.video
            <= self._segment_seconds * high
        ):
            logger.debug(
                f"[AV] {uri}: ignoring {segment.name}, "
                f"implausible video duration {measured.video:.1f}s"
            )
            return None

        if measured.audio is None:
            # The stream genuinely carries no audio track; nothing to compare.
            return None

        return measured.audio_deficit

    # --- reporting ------------------------------------------------------

    def status(self) -> dict:
        return {
            "enabled": True,
            "interval_seconds": self._interval,
            "threshold_seconds": self._threshold,
            "cooldown_seconds": self._cooldown,
            # Snapshot first: this is called from the web thread while the
            # watchdog thread may be adding a path.
            "paths": {uri: st.as_dict() for uri, st in list(self._state.items())},
        }

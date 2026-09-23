"""Read real per-track durations out of a fragmented MP4.

MediaMTX records fragmented MP4.  When the audio track's timeline drifts
behind the video track's, the recorder refuses to write the late samples
(`sample of track N received too late, discarding`) and the finished segment
ends up with a full-length video track and a short — or entirely empty —
audio track.  The size of that shortfall is the amount of audio thrown away.

Do NOT measure this with `ffprobe -show_entries stream=duration`.  A
fragmented MP4 carries `mdhd.duration == 0`, so when a declared audio track
received no samples at all ffprobe reports the *movie* duration for it and the
stream looks full-length.  Verified 2026-09-23 on real recordings: clips
reporting `duration=60.093563` for audio contain zero audio packets.  Sample
counts are the honest measure, and that is what this module reads.

ffprobe is not in the image anyway — the ffmpeg-for-homebridge tarball ships
the `ffmpeg` binary alone — so the durations are read straight out of the box
structure here: no subprocess, no extra dependency.

A track's duration is the sum of the sample durations recorded in every
`trun`, divided by that track's timescale.  Discarded samples were never
written into a `trun`, so a short audio track measures the loss exactly.
"""

import struct
from pathlib import Path
from typing import BinaryIO, NamedTuple, Optional

# Boxes whose payload is just more boxes and that we need to descend into.
_CONTAINERS = frozenset({b"moov", b"trak", b"mdia", b"moof", b"traf"})

# A size field larger than this means the file is corrupt or we lost sync;
# better to bail out than to seek wildly around a multi-GB recording.
_MAX_BOX_SIZE = 1 << 34

_HANDLER_VIDEO = b"vide"
_HANDLER_AUDIO = b"soun"


class TrackDurations(NamedTuple):
    """Per-track measurement of one recording segment.

    `video`/`audio` are seconds of samples actually written, or None when the
    file declares no such track.  A declared-but-empty track reads 0.0, which
    is the total-loss case and must stay distinct from None.

    `ok` is False when the file could not be parsed as fragmented MP4 (a `.ts`
    segment, a truncated file, a file still being written).  Callers must
    treat that as "no measurement", never as "no loss".
    """

    video: Optional[float]
    audio: Optional[float]
    ok: bool = True

    @property
    def audio_deficit(self) -> Optional[float]:
        """Seconds of audio missing relative to video, None if not comparable."""
        if not self.ok or self.video is None or self.audio is None:
            return None
        return max(0.0, self.video - self.audio)


_NO_MEASUREMENT = TrackDurations(None, None, False)


class _Track:
    __slots__ = ("timescale", "handler", "ticks")

    def __init__(self) -> None:
        self.timescale: int = 0
        self.handler: bytes = b""
        self.ticks: int = 0

    @property
    def seconds(self) -> Optional[float]:
        # No timescale means the track was never described in `moov`; that is
        # unknown, not zero.  Zero ticks with a known timescale is a real
        # measurement: the track exists and received nothing.
        if not self.timescale:
            return None
        return self.ticks / self.timescale


class _Parser:
    """Single-pass reader.  Only box headers and small payloads are read;
    `mdat` is stepped over with a seek so media bytes never hit memory."""

    def __init__(self, fh: BinaryIO) -> None:
        self.fh = fh
        self.tracks: dict[int, _Track] = {}
        # Set when a box is too short to read, or when a fragment carries no
        # usable durations.  Under-counting a track would read as audio loss
        # and trigger a needless rebuild, so give up instead of guessing.
        self.failed = False
        # Scratch used while inside one `trak` / one `traf`.
        self._trak_id: Optional[int] = None
        self._trak_timescale: int = 0
        self._trak_handler: bytes = b""
        self._traf_id: Optional[int] = None
        self._traf_default_duration: int = 0

    def _read_header(self, limit: int):
        """Return (type, total_size, header_size) or (None, None, None)."""
        start = self.fh.tell()
        head = self.fh.read(8)
        if len(head) < 8:
            return None, None, None
        size, btype = struct.unpack(">I4s", head)
        header = 8
        if size == 1:
            ext = self.fh.read(8)
            if len(ext) < 8:
                return None, None, None
            size = struct.unpack(">Q", ext)[0]
            header = 16
        elif size == 0:
            # Box runs to the end of the file.
            size = limit - start
        if size < header or size > _MAX_BOX_SIZE or start + size > limit:
            return None, None, None
        return btype, size, header

    def walk(self, limit: int) -> bool:
        while self.fh.tell() < limit:
            start = self.fh.tell()
            btype, size, _header = self._read_header(limit)
            if btype is None:
                return False
            end = start + size

            if btype == b"trak":
                self._trak_id = None
                self._trak_timescale = 0
                self._trak_handler = b""
                if not self.walk(end):
                    return False
                self._commit_trak()
            elif btype == b"traf":
                self._traf_id = None
                self._traf_default_duration = 0
                if not self.walk(end):
                    return False
            elif btype in _CONTAINERS:
                if not self.walk(end):
                    return False
            else:
                reader = _LEAF_READERS.get(btype)
                if reader:
                    reader(self, self.fh.read(end - self.fh.tell()))

            self.fh.seek(end)
        return True

    def _commit_trak(self) -> None:
        if self._trak_id is None:
            return
        track = self.tracks.setdefault(self._trak_id, _Track())
        track.timescale = self._trak_timescale
        track.handler = self._trak_handler

    # --- leaf boxes -----------------------------------------------------

    def _read_tkhd(self, data: bytes) -> None:
        if len(data) < 4:
            return
        version = data[0]
        offset = 4 + (16 if version == 1 else 8)
        if len(data) < offset + 4:
            return
        self._trak_id = struct.unpack_from(">I", data, offset)[0]

    def _read_mdhd(self, data: bytes) -> None:
        if len(data) < 4:
            return
        version = data[0]
        offset = 4 + (16 if version == 1 else 8)
        if len(data) < offset + 4:
            return
        self._trak_timescale = struct.unpack_from(">I", data, offset)[0]

    def _read_hdlr(self, data: bytes) -> None:
        # version/flags(4) pre_defined(4) handler_type(4)
        if len(data) < 12:
            return
        self._trak_handler = data[8:12]

    def _read_tfhd(self, data: bytes) -> None:
        if len(data) < 8:
            return
        flags = struct.unpack_from(">I", data, 0)[0] & 0x00FFFFFF
        self._traf_id = struct.unpack_from(">I", data, 4)[0]
        offset = 8
        if flags & 0x000001:  # base-data-offset
            offset += 8
        if flags & 0x000002:  # sample-description-index
            offset += 4
        if flags & 0x000008:  # default-sample-duration
            if len(data) < offset + 4:
                self.failed = True
                return
            self._traf_default_duration = struct.unpack_from(">I", data, offset)[0]

    def _read_trun(self, data: bytes) -> None:
        if self._traf_id is None or len(data) < 8:
            self.failed = True
            return
        flags = struct.unpack_from(">I", data, 0)[0] & 0x00FFFFFF
        sample_count = struct.unpack_from(">I", data, 4)[0]
        offset = 8
        if flags & 0x000001:  # data-offset
            offset += 4
        if flags & 0x000004:  # first-sample-flags
            offset += 4

        has_duration = bool(flags & 0x000100)
        per_sample = (
            (4 if has_duration else 0)
            + (4 if flags & 0x000200 else 0)
            + (4 if flags & 0x000400 else 0)
            + (4 if flags & 0x000800 else 0)
        )

        track = self.tracks.setdefault(self._traf_id, _Track())

        if not has_duration:
            # Durations are implied by the traf default.  MediaMTX leaves the
            # `trex` defaults at zero, so without a traf default there is
            # nothing to measure and the track would silently read short.
            if sample_count and not self._traf_default_duration:
                self.failed = True
                return
            track.ticks += sample_count * self._traf_default_duration
            return

        if len(data) < offset + sample_count * per_sample:
            self.failed = True
            return
        total = 0
        for _ in range(sample_count):
            total += struct.unpack_from(">I", data, offset)[0]
            offset += per_sample
        track.ticks += total


_LEAF_READERS = {
    b"tkhd": _Parser._read_tkhd,
    b"mdhd": _Parser._read_mdhd,
    b"hdlr": _Parser._read_hdlr,
    b"tfhd": _Parser._read_tfhd,
    b"trun": _Parser._read_trun,
}


def track_durations(path) -> TrackDurations:
    """Measure the video and audio tracks of one fMP4 recording segment."""
    file_path = Path(path)
    try:
        size = file_path.stat().st_size
    except OSError:
        return _NO_MEASUREMENT
    if size < 16:
        return _NO_MEASUREMENT

    try:
        with file_path.open("rb") as fh:
            parser = _Parser(fh)
            if not parser.walk(size) or parser.failed:
                # Lost sync, or a fragment we could not measure: whatever we
                # accumulated covers an unknown fraction of the file and would
                # look like huge loss.
                return _NO_MEASUREMENT
    except (OSError, struct.error):
        return _NO_MEASUREMENT

    video = audio = None
    for track in parser.tracks.values():
        if track.handler == _HANDLER_VIDEO and video is None:
            video = track.seconds
        elif track.handler == _HANDLER_AUDIO and audio is None:
            audio = track.seconds
    return TrackDurations(video, audio, True)

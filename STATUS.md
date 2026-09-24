# Status

Working notes for this fork: what it is, what has been fixed, what is still
open. Last updated **2026-09-24**, at **v4.3.17**.

This is `panchopin/docker-wyze-bridge`, a fork of `thatdaveguy1/docker-wyze-bridge`,
running as the Home Assistant add-on `63b085ed_docker_wyze_bridge_v4_panchopin`
from `ghcr.io/panchopin/docker-wyze-bridge`. It exists because the upstream
build did not support the Wyze Cam v4 (`HL_CAM4`); see
[`app/patches/go2rtc/README.md`](app/patches/go2rtc/README.md) for the other
reason it now diverges.

## The two camera routes

Almost everything here depends on which route a camera takes, and they fail
differently:

| | native | KVS |
|---|---|---|
| cameras | `HL_CAM4` (Cam v4) — currently only `main-bedroom` | `WYZE_CAKP2JFUS` (Cam v3) — the rest |
| chain | camera → go2rtc sidecar → RTSP → MediaMTX | camera → Wyze KVS → `whep_proxy` → WHEP → MediaMTX |
| MediaMTX path source | `rtsp://127.0.0.1:19554/<cam>`, always on | `whep://127.0.0.1:8080/whep/<cam>`, `sourceOnDemand` |
| audio codec | AAC 16 kHz, passed through untouched | G711, as the KVS stream delivers it |

Both decode timestamps through the same `rtptime.GlobalDecoder` in MediaMTX, so
both can end up with one track offset from the other — which is what the work
below has been about.

There is a third, older route in the code — the bridge's own TUTK client, which
pipes through ffmpeg and is where `AUDIO_CODEC` and the `pcm_mulaw` re-encode at
`app/wyzebridge/wyze_stream.py:731` live. Neither camera here takes it, so those
settings do nothing on this install; do not reason about the KVS cameras from
that code.

## What was fixed: recordings losing a track

Recordings were keeping full video and losing the audio. At its worst, **23 of
25 sampled clips held no audio at all**. It took four releases, two of which
were wrong, so the dead ends are recorded here too.

**Root cause.** Wyze cameras stamp each frame with only the microsecond part of
their clock: `pkg/tutk/frame.go` in go2rtc reads a field that counts 0..999999
and wraps every second, and the seconds themselves are never sent. go2rtc
rebuilt elapsed time from those deltas alone, so a gap longer than a second
vanished, and video and audio each zeroed on their own first frame and began at
unrelated origins. The audio timeline slid behind video, and MediaMTX's fMP4
recorder discards any sample landing before the current segment's start
(`sample of track N received too late, discarding`). Once the slide reached the
segment length, all of it went.

**Fixed by** building go2rtc from source with `app/patches/go2rtc/`, which gives
every track of a connection one shared origin, anchors a joining track by the
camera's clock rather than by when its frames turn up, and recovers the whole
seconds the camera cannot express — judged against how late that track normally
runs, and only once the shortfall holds. Still needed as of go2rtc `master`;
v1.9.14 is the latest release and the region is unchanged there, so upgrading
does not help. **Good candidate for an upstream PR.**

**Backstopped by** `app/wyzebridge/av_watchdog.py`, which measures finished
recordings and rebuilds a path when a track comes up short. It should rarely
have anything to do now, and stays on because it is the only thing that would
report a recurrence.

| release | state of `main-bedroom` |
|---|---|
| 4.3.11 | 938 warnings/min, 23 of 25 clips with no audio |
| 4.3.12 | wrong patch — leaked 1.2s/min in the opposite direction |
| 4.3.13 | root cause fixed, ~1.09s residual left |
| 4.3.14 | watchdog widened to all five cameras and to either track |
| 4.3.15 | residual closed — **0 discards**, worst audio deficit 0.06s |
| 4.3.16 | frame reassembly tolerates reordering; broke A/V timing |
| 4.3.17 | timing fixed — **7/7 clips complete**, video and audio matching |

## Open

### Two cameras have not sent a frame in hours (look here first)

`kitchen-cam` was 12 hours stale and `living-room-cam` nearly three days, both
still reporting `connected: true`. Judge a camera by `img_time`, never by
`connected`. This matters for any measurement you take here: those two show
zero recording errors purely because they carry no video, which is easy to
misread as health.

### KVS recordings are still fragmented

`bedroom-cam` and `baby-cam` lose frames upstream, which leaves gaps in the
H264 picture order count, which makes mediacommon's DTS extractor give up with
`too many reordered frames` (its limit is 10; measured gaps run 11–22, i.e.
0.5–1.1s of missing video, about four times a minute). Each one restarts the
recorder. `bedroom-cam` was averaging 29.7s clips against an expected 60s, with
roughly 12% of the video lost.

Not fixed. It is upstream loss on the WebRTC path rather than anything the
bridge does, and the same cameras have a long-standing failure where they
return `503` in a loop for days. The native route's equivalent problem *was*
fixed — see below — but that fix does not apply here: these cameras reach
MediaMTX through `whep_proxy`, not through go2rtc.

### Smaller

- `whep_proxy` reconnect churn on the KVS route, entangled with the above.
- `/kvs-config/<cam>` returns HTTP 500 when Wyze answers `401` to
  `wakeup_kvs_camera` — an unhandled `requests.HTTPError` reaching Flask
  (`app/wyzecam/api.py`, `app/frontend.py:415`).
- Log volume: the fixes in `LOG_NOISE_FIX_PROPOSAL.md` (2026-09-01) are still
  unapplied.

### Fixed along the way: the native route fragmenting

go2rtc's frame reassembler wanted packets in strict order and threw the frame
away on the first one out of place — and since its reset also cleared
`frameNo`, every remaining packet of that frame was dropped in turn, one
displaced packet costing the whole picture. With keyframes running to ~137
packets and round-trips peaking past 500ms on this network, that was close to a
coin toss per keyframe. Lost keyframes stalled the stream, MediaMTX's
`readTimeout` expired, and recordings came out in pieces.

Reassembly now holds out-of-order packets (4.3.16), and a frame is timed by its
first packet rather than by the straggler that completed it (4.3.17) — timing
it by the straggler made video look progressively late and pushed it ahead of
audio, which cost ~20s of audio per clip until it was caught.

## Things that will mislead you

**`ffprobe -show_entries stream=duration` lies about fragmented MP4.** These
recordings carry `mdhd.duration = 0`, so an audio track that received *nothing*
still reports the full movie duration and looks healthy. This hid the problem
for a day. Count samples instead — `ffprobe -select_streams a -count_packets`,
or `app/wyzebridge/fmp4_probe.py`, which reads per-track durations out of the
box structure with no subprocess (there is no `ffprobe` in the image anyway; the
ffmpeg-for-homebridge tarball ships `ffmpeg` alone).

**"track 2" is not always audio.** The number follows the order the recorder
declares, which differs per camera and can even flip between restarts:
`recording 2 tracks (H264, MPEG-4 Audio)` makes audio track 2, while
`(G711, H264)` makes *video* track 2. On the KVS route it has been video being
discarded, not audio.

**A short clip is usually not data loss.** A recorder restart leaves a fragment
where both tracks are short together. Only treat a segment as evidence when at
least one track ran the full length.

**Audio running past the last video frame is normal.** Segments are cut on
video; `kitchen-cam` spills about 1.7s while losing nothing.

**The offset is per connection.** It is cleared only by reconnecting the path's
source, never by restarting the recorder. `GET :5000/restart/rtsp_server`
restarts MediaMTX alone and clears it across the board.

## Working on it

Tests: `python3 -m unittest discover -s tests -t .` — note that a good number
fail outside the container for missing dependencies, so compare against a
baseline rather than expecting green.

`home_assistant/` and `.ha_live_addon/` are **generated** by `scripts/build.sh`
from `app/` plus `runtime_overlays/<target>/`. Edit the canonical copy and
mirror; `scripts/build.sh --check` reports drift (some is pre-existing).

Releasing is partly manual and the workflow is often left disabled — bump
`home_assistant/config.yml` and `app/.env`, tag, then `gh workflow enable` and
`gh workflow run --ref <tag>`, because a plain tag push does not trigger a
build. Roughly 20 minutes, then `ha store reload` and `ha addons update` on the
HA host.

The full investigation, with the measurements behind every claim above, is in
the operator's notes at
`hass-connect/notes/2026-09-22-audio-discard-diagnosis.md`.

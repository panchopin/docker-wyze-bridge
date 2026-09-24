# Status

Working notes for this fork: what it is, what has been fixed, what is still
open. Last updated **2026-09-24**, at **v4.3.15**.

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

## Open

### Recordings are being fragmented (next up)

Clips are being cut into 6–30s pieces instead of running the full 60s. In one
10-minute window: **19 `detected drift between recording duration and absolute
time` and 14 `too many reordered frames`**, each of which restarts the recorder.
Concentrated on the KVS cameras — `bedroom-cam` (18) and `kitchen-cam` (11),
against 4 for `main-bedroom`.

Not yet diagnosed. Worth keeping in mind that these may be the cameras'
own connectivity rather than anything in the bridge: the KVS route has a
separate, long-standing failure where a camera returns `503` in a loop for days
(see `wyze-per-camera-404-outages` in the operator's notes).

### Smaller

- `whep_proxy` reconnect churn on the KVS route, entangled with the above.
- `/kvs-config/<cam>` returns HTTP 500 when Wyze answers `401` to
  `wakeup_kvs_camera` — an unhandled `requests.HTTPError` reaching Flask
  (`app/wyzecam/api.py`, `app/frontend.py:415`).
- Log volume: the fixes in `LOG_NOISE_FIX_PROPOSAL.md` (2026-09-01) are still
  unapplied.

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

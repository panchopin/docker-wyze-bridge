# go2rtc patches

Applied to a pinned go2rtc checkout at image build time, so the binary we ship
differs from the upstream release. Keep `GO2RTC_VERSION` in the Dockerfiles in
step with the tag these were written against.

## 0001-tutk-shared-timebase-and-whole-second-recovery

Against **v1.9.14**. Still needed as of go2rtc `master` on 2026-09-23 — the
region is unchanged there and v1.9.14 is the latest release, so upgrading does
not help.

Wyze cameras stamp each frame with the microsecond part of their clock only:
`pkg/tutk/frame.go` reads a field that counts 0..999999 and wraps every second,
and the seconds themselves are never sent. `tsTracker.update()` rebuilds
elapsed time from those deltas alone, which fails in two ways:

1. **Gaps longer than a second vanish.** The wrap branch can only assume a
   single wrap, so a 1.4s stall reads as 0.4s and a whole second is lost from
   that track's timeline, permanently.
2. **The tracks have unrelated origins.** `videoTS` and `audioTS` each zero on
   their own first frame, so they start out offset by however long the second
   track took to appear.

Together these let the audio timeline slip arbitrarily far behind video. That
is not cosmetic downstream: MediaMTX's fMP4 recorder refuses samples that fall
before the current segment's start (`sample of track N received too late,
discarding`), so recordings lose audio — and once the slip reaches the segment
length, they lose *all* of it. Measured on this install: 23 of 25 sampled clips
held zero audio.

The patch gives every track of a connection one shared origin and uses frame
arrival time to recover the whole seconds the camera's counter cannot express.
Arrival time decides only *how many whole seconds* to add and where a track's
timeline starts; the camera's counter still supplies the exact sub-second
spacing, which is what A/V sync depends on.

**The correction is measured against that shared origin, not against the
previous frame.** The first version of this patch compared each frame with the
one before it, and shipped as 4.3.12 without fixing anything: audio arrives in
bursts, so a stall that merely *looks* like a lost second adds one that is
never taken back, and the errors integrate. Measured on the real camera after
4.8 minutes, video read 285.1s while audio read 291.3s — a runaway of about
1.2s per minute, in the opposite direction from the original bug. Closing the
loop on a fixed origin lets jitter average out instead of accumulating, and the
correction only ever *adds* seconds, which keeps the timeline monotonic for
free. Overshoot is self-limiting: once the timeline passes real time the drift
drops below a second and nothing further is added.

`pkg/tutk/frame_ts_test.go` comes with the patch and includes the pre-patch
algorithm, so each scenario is shown failing against the old code and passing
against the new one.

`pkg/tutk/frame_ts_sim_test.go` replays ten minutes of frame spacing measured
off the real camera, with audio delivered in bursts, and carries the
per-frame version alongside for comparison. Calibrated against the live
measurement above: the per-frame version walks 12.0s apart over that run, the
shared-origin version ends 0.03s apart with 99.4% of samples inside 0.5s.

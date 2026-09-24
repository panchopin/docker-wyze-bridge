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

**A track joins the shared timeline by the camera's clock, not by when its
frames turn up.** Both tracks are stamped from one clock inside the camera —
measured on a real HL_CAM4 their sub-second readings sit within about 150ms of
each other — so the signed distance between a joining frame and the most recent
frame already placed gives their true separation. Anchoring on arrival instead
carries whatever the difference in delivery latency happens to be, and that
offset then lasts for the life of the connection.

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

**And the shortfall is judged against how late that track normally runs, and
only after it holds for several frames.** A stall in delivery looks exactly
like a second genuinely lost on the frame it lands on; the two only separate
afterwards, when delivery catches back up and a real loss would not have.
4.3.13 acted immediately and against zero, so one hiccup added a second that
was never given back — which is the ~1.09s residual the camera was measured
sitting at, just past the one second where MediaMTX starts discarding. The test
suite runs the 4.3.13 shape through a single 1.3s stall for comparison: it ends
a full second ahead of the camera, this version lands exactly on it.

Sub-second delivery lags are handled exactly; a lag of half a second or more is
not, and cannot be. The camera sends only the microsecond part of its clock, so
such a lag is indistinguishable from a frame that really was captured that much
later — and MediaMTX stops accepting a track once it is a second behind the
segment, so a genuine lag that large costs data whatever we do.

`pkg/tutk/frame_ts_test.go` comes with the patch and includes the pre-patch
algorithm, so each scenario is shown failing against the old code and passing
against the new one.

`pkg/tutk/frame_ts_sim_test.go` replays ten minutes of frame spacing measured
off the real camera, with audio delivered in bursts, and carries the
per-frame version alongside for comparison. Calibrated against the live
measurement above: the per-frame version walks 12.0s apart over that run, the
shared-origin version ends 0.03s apart with 99.4% of samples inside 0.5s.

## The same patch also repairs frame reassembly

`pkg/tutk/frame.go` reassembles each frame from the packets the camera sends —
a 2K keyframe takes well over a hundred — and required them strictly in order.
Any packet arriving out of sequence threw the whole frame away.

Worse, the reset cleared `frameNo` along with everything else, so every packet
still to come for that same frame then looked like the start of a new one, was
reset again, and dropped in turn. One displaced packet cost the entire picture
and printed a log line per packet on its way out. Seen live, sixteen
consecutive `[OOO]` lines for a single frame:

```
[OOO] ch=0x05 #19294 pktTotal=137 expected pkt 0, got 117 - reset
[OOO] ch=0x05 #19294 pktTotal=137 expected pkt 0, got 122 - reset
...
```

Reordering is ordinary on a busy wireless link — measured on this network,
round-trip times to the cameras average 30ms and peak past 500ms. Losing
keyframes to it stalls the stream, which downstream shows up as MediaMTX's
`readTimeout` expiring and reconnecting, and recordings cut into fragments.

Packets arriving ahead of their turn are now held until the gap ahead of them
fills, capped so that a packet which never arrives cannot grow the hold without
bound. A frame is still never emitted with a hole in it. The tests carry the
previous behaviour alongside, so the frame it dropped and this one recovers is
the same frame.

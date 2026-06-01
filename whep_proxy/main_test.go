package main

import (
	"errors"
	"io"
	"os"
	"strings"
	"testing"
	"time"

	"github.com/gorilla/websocket"
	"github.com/pion/rtp"
	"github.com/pion/webrtc/v3"
)

func TestShouldForwardVideoPacketDropsPreIDRFrames(t *testing.T) {
	stream := &WebRTCStream{}

	nonIDR := &rtp.Packet{Payload: []byte{0x41, 0x00}}
	if stream.shouldForwardVideoPacket(nonIDR) {
		t.Fatal("expected pre-IDR video packet to be dropped until stream is primed")
	}

	stream.videoPrimed.Store(true)
	if !stream.shouldForwardVideoPacket(nonIDR) {
		t.Fatal("expected video packet to pass once stream is primed")
	}
}

func TestShouldForwardVideoPacketPrimesOnFirstIDR(t *testing.T) {
	stream := &WebRTCStream{}
	idrStart := &rtp.Packet{Payload: []byte{0x7c, 0x85, 0x00}}

	if !stream.shouldForwardVideoPacket(idrStart) {
		t.Fatal("expected first IDR packet to prime and pass through")
	}

	if !stream.videoPrimed.Load() {
		t.Fatal("expected first IDR to mark stream video primed")
	}
}

func TestOutputTracksRequireReadyMedia(t *testing.T) {
	videoTrack, err := webrtc.NewTrackLocalStaticRTP(
		webrtc.RTPCodecCapability{MimeType: webrtc.MimeTypeH264},
		"video",
		"pion",
	)
	if err != nil {
		t.Fatalf("create video track: %v", err)
	}
	audioTrack, err := webrtc.NewTrackLocalStaticRTP(
		webrtc.RTPCodecCapability{MimeType: webrtc.MimeTypePCMU, ClockRate: 8000, Channels: 2},
		"audio",
		"pion",
	)
	if err != nil {
		t.Fatalf("create audio track: %v", err)
	}

	stream := &WebRTCStream{videoTrack: videoTrack, audioTrack: audioTrack}
	if got := len(stream.outputTracks()); got != 0 {
		t.Fatalf("expected no output tracks before upstream media is ready, got %d", got)
	}

	stream.audioReady.Store(true)
	if got := len(stream.outputTracks()); got != 0 {
		t.Fatalf("expected no output tracks while only audio is ready, got %d", got)
	}

	stream.videoReady.Store(true)
	if got := len(stream.outputTracks()); got != 1 {
		t.Fatalf("expected video-only output before real audio packets arrive, got %d", got)
	}

	stream.markAudioPacketSeen()
	if got := len(stream.outputTracks()); got != 2 {
		t.Fatalf("expected both output tracks once video and real audio packets are ready, got %d", got)
	}
	if !stream.canReuse() {
		t.Fatal("expected stream with ready media to be reusable")
	}
	stream.videoReady.Store(false)
	stream.audioReady.Store(false)
	if stream.canReuse() {
		t.Fatal("expected stream without upstream session or ready media to stay non-reusable")
	}
	stream.setUpstream(&UpstreamSession{startedAt: time.Now()})
	if !stream.canReuse() {
		t.Fatal("expected stream with recent upstream session to be reusable during startup")
	}
	stream.setUpstream(&UpstreamSession{startedAt: time.Now().Add(-startupReuseWindow - time.Second)})
	if stream.canReuse() {
		t.Fatal("expected stale upstream session without media to be replaced")
	}
}

func TestCreateAndSendOfferRejectsMissingPeerConnection(t *testing.T) {
	if err := createAndSendOffer("south-yard", nil); err == nil {
		t.Fatal("expected nil session to fail")
	}
	if err := createAndSendOffer("south-yard", &UpstreamSession{}); err == nil {
		t.Fatal("expected nil peer connection to fail")
	} else if !strings.Contains(err.Error(), "peer connection unavailable") {
		t.Fatalf("expected peer connection error, got %v", err)
	}
}

func TestUpstreamVideoOnlyMatchesConfiguredStreams(t *testing.T) {
	t.Setenv("WHEP_UPSTREAM_VIDEO_ONLY_STREAMS", "south-yard, south-yard-sub\thamster")

	for _, streamID := range []string{"south-yard", "south-yard-sub", "hamster"} {
		if !upstreamVideoOnly(streamID) {
			t.Fatalf("expected %s to be video-only", streamID)
		}
	}
	if upstreamVideoOnly("deck-sub") {
		t.Fatal("did not expect deck-sub to be video-only")
	}
}

func TestUpstreamVideoOnlySupportsWildcard(t *testing.T) {
	t.Setenv("WHEP_UPSTREAM_VIDEO_ONLY_STREAMS", "*")

	if !upstreamVideoOnly("deck-sub") {
		t.Fatal("expected wildcard to match any stream")
	}
}

func TestCanReuseStaleNoMediaStreamExpires(t *testing.T) {
	// A stream that has never produced media and whose streamCreatedAt is past
	// maxNoMediaAge must return canReuse()=false — even when reconnecting=true
	// or a fresh upstream session is present — to break the perpetual "new"
	// wedge where each reconnect resets the per-session startedAt clock.
	stream := &WebRTCStream{
		streamCreatedAt: time.Now().Add(-maxNoMediaAge - time.Second),
	}
	// No media ever, no upstream session yet.
	if stream.canReuse() {
		t.Fatal("expected stream with no media and expired maxNoMediaAge to be non-reusable")
	}
	// Also non-reusable even when reconnecting.
	stream.reconnecting.Store(true)
	if stream.canReuse() {
		t.Fatal("expected reconnecting stream past maxNoMediaAge with no media to be non-reusable")
	}
	stream.reconnecting.Store(false)

	// Once media has ever flowed, the maxNoMediaAge guard must NOT fire:
	// existing reconnect / startup-window logic takes over instead.
	stream.hasEverHadMedia.Store(true)
	stream.setUpstream(&UpstreamSession{startedAt: time.Now()})
	if !stream.canReuse() {
		t.Fatal("expected stream that has had media (even past maxNoMediaAge) to remain reusable during startup window")
	}
}

func TestRecoveredStreamKeepsReadyStatusDuringReconnectWindow(t *testing.T) {
	videoTrack, err := webrtc.NewTrackLocalStaticRTP(
		webrtc.RTPCodecCapability{MimeType: webrtc.MimeTypeH264},
		"video",
		"pion",
	)
	if err != nil {
		t.Fatalf("create video track: %v", err)
	}
	audioTrack, err := webrtc.NewTrackLocalStaticRTP(
		webrtc.RTPCodecCapability{MimeType: webrtc.MimeTypePCMU, ClockRate: 8000, Channels: 2},
		"audio",
		"pion",
	)
	if err != nil {
		t.Fatalf("create audio track: %v", err)
	}
	peerConnection, err := createPeerConnection(WebRTCConfig{})
	if err != nil {
		t.Fatalf("create peer connection: %v", err)
	}
	defer peerConnection.Close()

	stream := &WebRTCStream{
		streamID:          "deck-sub",
		videoTrack:        videoTrack,
		audioTrack:        audioTrack,
		streamCreatedAt:   time.Now().Add(-10 * time.Minute),
		recoveryStartedAt: time.Now(),
	}
	stream.videoReady.Store(true)
	stream.audioReady.Store(true)
	stream.audioPacketsSeen.Store(42)
	stream.hasEverHadMedia.Store(true)
	stream.reconnecting.Store(true)
	stream.setUpstream(&UpstreamSession{peerConnection: peerConnection, startedAt: time.Now()})

	status := stream.status()
	if got := status["upstream_state"]; got != "recovering" {
		t.Fatalf("expected reconnecting previously healthy stream to report recovering, got %v", got)
	}
	if got := status["video_ready"]; got != true {
		t.Fatalf("expected video_ready to stay true during bounded recovery, got %v", got)
	}
	if got := status["audio_packets_seen"]; got != uint64(42) {
		t.Fatalf("expected audio packet count to stay available during bounded recovery, got %v", got)
	}
	if !stream.canReuse() {
		t.Fatal("expected stream inside recovery window to remain reusable")
	}
}

func TestRecoveredStreamExpiresAfterRecoveryWindow(t *testing.T) {
	stream := &WebRTCStream{
		streamID:          "deck-sub",
		streamCreatedAt:   time.Now().Add(-10 * time.Minute),
		recoveryStartedAt: time.Now().Add(-maxRecoveryAge - time.Second),
	}
	stream.videoReady.Store(true)
	stream.hasEverHadMedia.Store(true)

	if stream.canReuse() {
		t.Fatal("expected previously healthy stream past recovery window to become non-reusable")
	}
}

func TestBufferVideoParameterSetReassemblesFragmentedSTAPA(t *testing.T) {
	stream := &WebRTCStream{}

	stapAWithoutHeader := []byte{
		0x00, 0x02, 0x67, 0xaa,
		0x00, 0x02, 0x68, 0xbb,
	}
	start := &rtp.Packet{
		Header:  rtp.Header{SequenceNumber: 10},
		Payload: append([]byte{0x7c, 0x98}, stapAWithoutHeader[:4]...),
	}
	end := &rtp.Packet{
		Header:  rtp.Header{SequenceNumber: 11},
		Payload: append([]byte{0x7c, 0x58}, stapAWithoutHeader[4:]...),
	}

	stream.bufferVideoParameterSet(start)
	stream.bufferVideoParameterSet(end)

	if stream.videoParamPacket == nil {
		t.Fatal("expected fragmented STAP-A SPS/PPS to be buffered as a replay packet")
	}
	if stream.videoSPSBytes != 2 || stream.videoPPSBytes != 2 {
		t.Fatalf("expected SPS/PPS sizes 2/2, got %d/%d", stream.videoSPSBytes, stream.videoPPSBytes)
	}
	if got := stream.videoParamPacket.Payload[0] & 0x1f; got != 24 {
		t.Fatalf("expected reassembled STAP-A payload, got nalu type %d", got)
	}
}

func TestReplayFailureThresholdForcesReconnect(t *testing.T) {
	stream := &WebRTCStream{}
	for i := int32(1); i < maxVideoParamReplayFailures; i++ {
		if stream.recordVideoReplayFailure() {
			t.Fatalf("failure %d should not cross reconnect threshold", i)
		}
	}
	if !stream.recordVideoReplayFailure() {
		t.Fatal("expected third consecutive replay failure to cross reconnect threshold")
	}
}

func TestNoVideoReconnectAttemptsForceRecreate(t *testing.T) {
	stream := &WebRTCStream{}
	stream.reconnecting.Store(true)
	for i := int32(0); i < maxNoVideoReconnectAttempts; i++ {
		stream.markReconnectAttempt(1)
	}
	if stream.shouldForceRecreateNoVideo() {
		t.Fatal("expected three no-video reconnect attempts to remain below force-recreate threshold")
	}

	stream.markReconnectAttempt(1)
	if !stream.shouldForceRecreateNoVideo() {
		t.Fatal("expected fourth no-video reconnect attempt to force recreate")
	}

	stream.videoReady.Store(true)
	if stream.shouldForceRecreateNoVideo() {
		t.Fatal("expected video-ready stream not to force recreate")
	}
}

func TestReapStaleStreamsRecreatesNoVideoReconnectWedge(t *testing.T) {
	streamsMu.Lock()
	previousStreams := streams
	streams = make(map[string]*WebRTCStream)
	stream := &WebRTCStream{streamID: "south-yard-sub"}
	stream.reconnecting.Store(true)
	for i := int32(0); i < maxNoVideoReconnectAttempts+1; i++ {
		stream.markReconnectAttempt(1)
	}
	streams[stream.streamID] = stream
	streamsMu.Unlock()
	defer func() {
		streamsMu.Lock()
		streams = previousStreams
		streamsMu.Unlock()
	}()

	previousRecreate := recreateStreamFn
	called := make(chan string, 1)
	recreateStreamFn = func(streamID string, current *WebRTCStream, reason string) error {
		if current != stream {
			t.Fatalf("expected current stream pointer to be passed to recreate")
		}
		called <- streamID + ":" + reason
		return nil
	}
	defer func() { recreateStreamFn = previousRecreate }()

	if got := reapStaleStreams(); got != 1 {
		t.Fatalf("expected one stale stream candidate, got %d", got)
	}
	select {
	case msg := <-called:
		if !strings.Contains(msg, "south-yard-sub:no video after 4 reconnect attempts") {
			t.Fatalf("unexpected recreate call: %s", msg)
		}
	case <-time.After(time.Second):
		t.Fatal("expected stale stream recreate to be called")
	}
}

func TestClassifyWSReadErrorTreatsGoingAwayAsNormal(t *testing.T) {
	closeInfo := classifyWSReadError(&websocket.CloseError{Code: websocket.CloseGoingAway, Text: "Going away"})
	if !closeInfo.normal {
		t.Fatal("expected close 1001 to be classified as normal")
	}
	if closeInfo.code != websocket.CloseGoingAway {
		t.Fatalf("expected code %d, got %d", websocket.CloseGoingAway, closeInfo.code)
	}
}

func TestShouldReconnectOnNormalWSClosure(t *testing.T) {
	tests := []struct {
		name       string
		state      webrtc.PeerConnectionState
		videoReady bool
		audioReady bool
		want       bool
	}{
		{
			name:  "connected peer stays alive",
			state: webrtc.PeerConnectionStateConnected,
			want:  false,
		},
		{
			name:       "ready video stays alive",
			state:      webrtc.PeerConnectionStateConnecting,
			videoReady: true,
			want:       false,
		},
		{
			name:       "audio-only peer reconnects",
			state:      webrtc.PeerConnectionStateConnecting,
			audioReady: true,
			want:       true,
		},
		{
			name:  "new peer reconnects",
			state: webrtc.PeerConnectionStateNew,
			want:  true,
		},
		{
			name:       "failed peer reconnects",
			state:      webrtc.PeerConnectionStateFailed,
			videoReady: true,
			want:       true,
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			got := shouldReconnectOnNormalWSClosure(tt.state, tt.videoReady, tt.audioReady)
			if got != tt.want {
				t.Fatalf("expected %t, got %t", tt.want, got)
			}
		})
	}
}

func TestIsTerminalRefreshErrorRecognizesMissingStream(t *testing.T) {
	err := &refreshConfigError{
		statusCode: 404,
		body:       `{"error":"camera [south-yard] not found"}`,
	}
	if !isTerminalRefreshError(err) {
		t.Fatal("expected 404 refresh config error to stop reconnecting")
	}
}

func TestIsTerminalRefreshErrorIgnoresRetryableRefreshFailures(t *testing.T) {
	err := &refreshConfigError{
		statusCode: 503,
		body:       `{"error":"KVS config not ready for south-yard"}`,
	}
	if isTerminalRefreshError(err) {
		t.Fatal("expected retryable refresh config error to keep reconnecting")
	}
	if isTerminalRefreshError(errors.New("boom")) {
		t.Fatal("expected unrelated error to stay non-terminal")
	}
}

func TestKVSConfigURLUsesExplicitPort(t *testing.T) {
	t.Setenv("KVS_CONFIG_HOST", "bridge.local")
	t.Setenv("KVS_CONFIG_PORT", "55000")
	t.Setenv("WB_APP_PORT", "5000")

	got := kvsConfigURL("south-yard-sub")
	want := "http://bridge.local:55000/kvs-config/south-yard-sub"
	if got != want {
		t.Fatalf("expected %q, got %q", want, got)
	}
}

func TestKVSConfigURLFallsBackToBridgeAppPort(t *testing.T) {
	t.Setenv("KVS_CONFIG_PORT", "")
	t.Setenv("WB_APP_PORT", "55000")

	got := kvsConfigURL("garage-sub")
	want := "http://127.0.0.1:55000/kvs-config/garage-sub"
	if got != want {
		t.Fatalf("expected %q, got %q", want, got)
	}
}

func TestCloseNormalRotationWebsocketNilSession(t *testing.T) {
	closeNormalRotationWebsocket(nil)
}

func TestShouldLogTrackEndSuppressesEOF(t *testing.T) {
	if shouldLogTrackEnd(io.EOF) {
		t.Fatal("expected EOF track end to be suppressed outside debug logging")
	}
	if !shouldLogTrackEnd(errors.New("boom")) {
		t.Fatal("expected non-EOF track end to remain visible")
	}
}

func TestWHEPTraceEnabledMatchesConfiguredStream(t *testing.T) {
	t.Setenv("WHEP_TRACE_STREAM", "dog-run")
	if !whepTraceEnabled("dog-run") {
		t.Fatal("expected configured trace stream to be enabled")
	}
	if whepTraceEnabled("deck") {
		t.Fatal("expected non-configured stream to remain untraced")
	}
	if os.Getenv("WHEP_TRACE_STREAM") != "dog-run" {
		t.Fatal("expected trace env to stay available during test")
	}
}

func TestWHEPTraceDisabledWithoutConfiguredStream(t *testing.T) {
	t.Setenv("WHEP_TRACE_STREAM", "")
	if whepTraceEnabled("dog-run") {
		t.Fatal("expected tracing to stay disabled without explicit opt-in")
	}
	if whepTraceEnabled("deck") {
		t.Fatal("expected other streams to remain untraced by default")
	}
}

func TestSanitizeLogURLRedactsQueryString(t *testing.T) {
	got := sanitizeLogURL("wss://example.test/signal?token=secret&x=1")
	if got != "wss://example.test/signal" {
		t.Fatalf("expected sanitized URL, got %q", got)
	}
}

func TestIsLoopbackRemoteAddr(t *testing.T) {
	if !isLoopbackRemoteAddr("127.0.0.1:8080") {
		t.Fatal("expected IPv4 loopback to be allowed")
	}
	if !isLoopbackRemoteAddr("[::1]:8080") {
		t.Fatal("expected IPv6 loopback to be allowed")
	}
	if isLoopbackRemoteAddr("10.0.0.5:8080") {
		t.Fatal("expected non-loopback remote address to be rejected")
	}
}

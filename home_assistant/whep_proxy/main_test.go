package main

import (
	"errors"
	"io"
	"os"
	"testing"

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

	stream.videoReady.Store(true)
	if got := len(stream.outputTracks()); got != 1 {
		t.Fatalf("expected only video track once video is ready, got %d", got)
	}

	stream.audioReady.Store(true)
	if got := len(stream.outputTracks()); got != 2 {
		t.Fatalf("expected both output tracks once media is ready, got %d", got)
	}
	if !stream.canReuse() {
		t.Fatal("expected stream with ready media to be reusable")
	}
	stream.videoReady.Store(false)
	stream.audioReady.Store(false)
	if stream.canReuse() {
		t.Fatal("expected stream without upstream session or ready media to stay non-reusable")
	}
	stream.setUpstream(&UpstreamSession{})
	if !stream.canReuse() {
		t.Fatal("expected stream with active upstream session to be reusable during startup")
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
			name:       "ready audio stays alive",
			state:      webrtc.PeerConnectionStateConnecting,
			audioReady: true,
			want:       false,
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

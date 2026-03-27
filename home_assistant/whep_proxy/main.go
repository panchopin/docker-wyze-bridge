package main

import (
	"encoding/base64"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"log"
	"net"
	"net/http"
	"net/url"
	"os"
	"os/signal"
	"strconv"
	"strings"
	"sync"
	"sync/atomic"
	"time"

	"github.com/gorilla/mux"
	"github.com/gorilla/websocket"
	"github.com/pion/interceptor"
	"github.com/pion/rtcp"
	"github.com/pion/rtp"
	"github.com/pion/webrtc/v3"
)

type WebRTCStream struct {
	streamID          string
	configMu          sync.RWMutex
	config            WebRTCConfig
	upstreamMu        sync.RWMutex
	upstream          *UpstreamSession
	mediaMu           sync.RWMutex
	etag              string
	videoTrack        *webrtc.TrackLocalStaticRTP
	audioTrack        *webrtc.TrackLocalStaticRTP
	videoTrackMu      sync.Mutex
	audioTrackMu      sync.Mutex
	forwardWg         sync.WaitGroup
	videoSource       *webrtc.TrackRemote
	whepClients       atomic.Int32
	videoPLIRequested atomic.Bool
	videoParamPacket  *rtp.Packet
	videoSPSPacket    *rtp.Packet
	videoPPSPacket    *rtp.Packet
	videoSPSBytes     int
	videoPPSBytes     int
	videoOutSeq       uint16
	audioOutSeq       uint16
	videoOutSeqSet    bool
	audioOutSeqSet    bool
	videoReady        atomic.Bool
	videoPrimed       atomic.Bool
	audioReady        atomic.Bool
	upstreamAlive     atomic.Bool
	reconnecting      atomic.Bool
	destroyed         atomic.Bool
	videoReplayLogged atomic.Bool
	videoIDRLogged    atomic.Bool
	videoParamsMissed atomic.Bool
}

type UpstreamSession struct {
	peerConnection    *webrtc.PeerConnection
	wsConn            *websocket.Conn
	wsMu              sync.Mutex
	pendingCandidates []webrtc.ICECandidateInit
	remoteDescription *webrtc.SessionDescription
	correlationID     string
	recipientClientID string
	startedAt         time.Time
	normalCloseLogged atomic.Bool
	videoTrackLogged  atomic.Bool
	audioTrackLogged  atomic.Bool
}

type wsCloseInfo struct {
	code   int
	reason string
	normal bool
}

type ICEServer struct {
	URL        string `json:"url"`
	Username   string `json:"username"`
	Credential string `json:"credential"`
}

type WebRTCConfig struct {
	SignalingURL string      `json:"signaling_url"`
	ICEServers   []ICEServer `json:"ice_servers"`
	AuthToken    string      `json:"auth_token"`
	PhoneID      string      `json:"phone_id"`
}

var streams = make(map[string]*WebRTCStream)
var streamsMu sync.Mutex

func (stream *WebRTCStream) outputTracks() []*webrtc.TrackLocalStaticRTP {
	stream.mediaMu.RLock()
	defer stream.mediaMu.RUnlock()

	tracks := make([]*webrtc.TrackLocalStaticRTP, 0, 2)
	if stream.videoTrack != nil && stream.videoReady.Load() {
		tracks = append(tracks, stream.videoTrack)
	}
	if stream.audioTrack != nil && stream.audioReady.Load() {
		tracks = append(tracks, stream.audioTrack)
	}
	return tracks
}

func (stream *WebRTCStream) ensureETag() string {
	stream.mediaMu.Lock()
	defer stream.mediaMu.Unlock()

	if stream.etag == "" {
		stream.etag = fmt.Sprintf("\"%x\"", time.Now().UnixNano())
	}
	return stream.etag
}

func (stream *WebRTCStream) canReuse() bool {
	if stream == nil || stream.destroyed.Load() {
		return false
	}
	if stream.videoReady.Load() || stream.audioReady.Load() {
		return true
	}
	return stream.currentUpstream() != nil || stream.reconnecting.Load()
}

func (stream *WebRTCStream) setVideoSource(track *webrtc.TrackRemote) {
	stream.mediaMu.Lock()
	defer stream.mediaMu.Unlock()
	stream.videoSource = track
	stream.videoReady.Store(track != nil)
}

func (stream *WebRTCStream) setAudioReady(ready bool) {
	stream.audioReady.Store(ready)
}

func (stream *WebRTCStream) status() map[string]interface{} {
	upstreamState := ""
	if session := stream.currentUpstream(); session != nil && session.peerConnection != nil {
		upstreamState = session.peerConnection.ConnectionState().String()
	}

	return map[string]interface{}{
		"upstream_state": upstreamState,
		"upstream_alive": stream.upstreamAlive.Load(),
		"can_reuse":      stream.canReuse(),
		"video_ready":    stream.videoReady.Load(),
		"audio_ready":    stream.audioReady.Load(),
		"whep_clients":   stream.whepClients.Load(),
	}
}

func (stream *WebRTCStream) requestVideoKeyframe(reason string) error {
	stream.mediaMu.RLock()
	videoSource := stream.videoSource
	stream.mediaMu.RUnlock()
	session := stream.currentUpstream()
	var peerConnection *webrtc.PeerConnection
	if session != nil {
		peerConnection = session.peerConnection
	}

	if videoSource == nil || peerConnection == nil {
		if whepDebugEnabled() {
			log.Printf("[WHEP_PROXY] Skipping keyframe request (%s): video source unavailable", reason)
		}
		return nil
	}

	err := peerConnection.WriteRTCP([]rtcp.Packet{
		&rtcp.PictureLossIndication{MediaSSRC: uint32(videoSource.SSRC())},
	})
	if err != nil {
		return err
	}

	if whepDebugEnabled() && reason != "downstream rtcp feedback" && reason != "periodic downstream refresh" {
		log.Printf("[WHEP_PROXY] Requested keyframe (%s) for SSRC=%d", reason, videoSource.SSRC())
	}
	return nil
}

func classifyWSReadError(err error) wsCloseInfo {
	var closeErr *websocket.CloseError
	if errors.As(err, &closeErr) {
		reason := strings.TrimSpace(closeErr.Text)
		return wsCloseInfo{code: closeErr.Code, reason: reason, normal: closeErr.Code == websocket.CloseNormalClosure || closeErr.Code == websocket.CloseGoingAway}
	}
	if errors.Is(err, io.EOF) {
		return wsCloseInfo{reason: "EOF"}
	}
	return wsCloseInfo{}
}

func shouldLogTrackEnd(err error) bool {
	return !errors.Is(err, io.EOF)
}

func shouldLogRTCPEnd(err error) bool {
	return !errors.Is(err, io.EOF)
}

func logNormalClose(
	session *UpstreamSession,
	streamID string,
	closeInfo wsCloseInfo,
	peerState webrtc.PeerConnectionState,
	iceState webrtc.ICEConnectionState,
	videoReady bool,
	audioReady bool,
	upstreamAlive bool,
	whepClients int32,
) {
	if session == nil || !session.normalCloseLogged.CompareAndSwap(false, true) {
		return
	}
	reason := closeInfo.reason
	if reason == "" {
		reason = "normal closure"
	}
	log.Printf(
		"[WHEP_PROXY] Upstream session rotated for %s: websocket close code=%d reason=%q peer=%s ice=%s video_ready=%t audio_ready=%t upstream_alive=%t whep_clients=%d session_age=%s",
		streamID,
		closeInfo.code,
		reason,
		peerState.String(),
		iceState.String(),
		videoReady,
		audioReady,
		upstreamAlive,
		whepClients,
		time.Since(session.startedAt).Round(time.Millisecond),
	)
}

func shouldReconnectOnNormalWSClosure(state webrtc.PeerConnectionState, videoReady bool, audioReady bool) bool {
	switch state {
	case webrtc.PeerConnectionStateConnected:
		return false
	case webrtc.PeerConnectionStateFailed, webrtc.PeerConnectionStateClosed:
		return true
	}

	return !(videoReady || audioReady)
}

func closeNormalRotationWebsocket(session *UpstreamSession) {
	if session == nil {
		return
	}

	session.wsMu.Lock()
	defer session.wsMu.Unlock()
	if session.wsConn == nil {
		return
	}
	_ = session.wsConn.Close()
	session.wsConn = nil
}

func (stream *WebRTCStream) currentUpstream() *UpstreamSession {
	stream.upstreamMu.RLock()
	defer stream.upstreamMu.RUnlock()
	return stream.upstream
}

func (stream *WebRTCStream) getConfig() WebRTCConfig {
	stream.configMu.RLock()
	defer stream.configMu.RUnlock()
	return stream.config
}

func (stream *WebRTCStream) setConfig(config WebRTCConfig) {
	stream.configMu.Lock()
	stream.config = config
	stream.configMu.Unlock()
}

func (stream *WebRTCStream) setUpstream(session *UpstreamSession) {
	stream.upstreamMu.Lock()
	stream.upstream = session
	stream.upstreamMu.Unlock()
	stream.upstreamAlive.Store(session != nil)
}

func (stream *WebRTCStream) clearUpstreamIfCurrent(session *UpstreamSession) bool {
	stream.upstreamMu.Lock()
	defer stream.upstreamMu.Unlock()
	if stream.upstream != session {
		return false
	}
	stream.upstream = nil
	stream.upstreamAlive.Store(false)
	return true
}

func (stream *WebRTCStream) resetUpstreamMediaState() {
	stream.setVideoSource(nil)
	stream.setAudioReady(false)
	stream.videoPLIRequested.Store(false)
	stream.videoPrimed.Store(false)
	stream.videoReplayLogged.Store(false)
	stream.videoIDRLogged.Store(false)
	stream.videoParamsMissed.Store(false)
	stream.mediaMu.Lock()
	stream.videoParamPacket = nil
	stream.videoSPSPacket = nil
	stream.videoPPSPacket = nil
	stream.videoSPSBytes = 0
	stream.videoPPSBytes = 0
	stream.mediaMu.Unlock()
}

func closeUpstreamSession(session *UpstreamSession) {
	if session == nil {
		return
	}
	if session.wsConn != nil {
		session.wsMu.Lock()
		_ = session.wsConn.Close()
		session.wsConn = nil
		session.wsMu.Unlock()
	}
	if session.peerConnection != nil {
		_ = session.peerConnection.Close()
		session.peerConnection = nil
	}
}

func h264PacketInfo(payload []byte) (isIDR bool, desc string) {
	if len(payload) == 0 {
		return false, "empty"
	}

	naluType := payload[0] & 0x1F
	switch naluType {
	case 5:
		return true, "single-idr"
	case 24:
		types := make([]string, 0, 4)
		hasIDR := false
		for i := 1; i+2 <= len(payload); {
			naluSize := int(payload[i])<<8 | int(payload[i+1])
			i += 2
			if naluSize <= 0 || i+naluSize > len(payload) {
				break
			}
			aggType := payload[i] & 0x1F
			types = append(types, strconv.Itoa(int(aggType)))
			if aggType == 5 {
				hasIDR = true
			}
			i += naluSize
		}
		if len(types) == 0 {
			return false, "stap-a"
		}
		return hasIDR, "stap-a[" + strings.Join(types, ",") + "]"
	case 28:
		if len(payload) < 2 {
			return false, "fu-a-short"
		}
		start := payload[1]&0x80 != 0
		end := payload[1]&0x40 != 0
		origType := payload[1] & 0x1F
		if origType == 5 && start {
			return true, "fu-a-idr-start"
		}
		if origType == 5 && end {
			return false, "fu-a-idr-end"
		}
		return false, fmt.Sprintf("fu-a-%d", origType)
	default:
		return false, fmt.Sprintf("nalu-%d", naluType)
	}
}

func h264FUAState(payload []byte) (isFUA bool, start bool, end bool) {
	if len(payload) < 2 {
		return false, false, false
	}
	if payload[0]&0x1F != 28 {
		return false, false, false
	}
	return true, payload[1]&0x80 != 0, payload[1]&0x40 != 0
}

func cloneRTPPacket(pkt *rtp.Packet) *rtp.Packet {
	if pkt == nil {
		return nil
	}

	clone := &rtp.Packet{
		Header:      pkt.Header,
		PaddingSize: pkt.PaddingSize,
	}
	clone.CSRC = append([]uint32(nil), pkt.CSRC...)
	clone.Extensions = append([]rtp.Extension(nil), pkt.Extensions...)
	clone.Payload = append([]byte(nil), pkt.Payload...)
	clone.Raw = append([]byte(nil), pkt.Raw...)
	return clone
}

func parseSTAPAParameterSets(payload []byte) (int, int) {
	if len(payload) < 3 {
		return 0, 0
	}

	var spsBytes int
	var ppsBytes int
	for i := 1; i+2 <= len(payload); {
		naluSize := int(payload[i])<<8 | int(payload[i+1])
		i += 2
		if naluSize <= 0 || i+naluSize > len(payload) {
			break
		}

		switch payload[i] & 0x1F {
		case 7:
			spsBytes = naluSize
		case 8:
			ppsBytes = naluSize
		}
		i += naluSize
	}

	return spsBytes, ppsBytes
}

func (stream *WebRTCStream) bufferVideoParameterSet(pkt *rtp.Packet) {
	if pkt == nil || len(pkt.Payload) == 0 {
		return
	}

	naluType := pkt.Payload[0] & 0x1F

	stream.mediaMu.Lock()
	defer stream.mediaMu.Unlock()

	switch naluType {
	case 7:
		stream.videoParamPacket = nil
		stream.videoSPSPacket = cloneRTPPacket(pkt)
		stream.videoSPSBytes = len(pkt.Payload)
	case 8:
		stream.videoParamPacket = nil
		stream.videoPPSPacket = cloneRTPPacket(pkt)
		stream.videoPPSBytes = len(pkt.Payload)
	case 24:
		spsBytes, ppsBytes := parseSTAPAParameterSets(pkt.Payload)
		if spsBytes == 0 && ppsBytes == 0 {
			return
		}
		if spsBytes > 0 && ppsBytes > 0 {
			stream.videoParamPacket = cloneRTPPacket(pkt)
			stream.videoSPSPacket = nil
			stream.videoPPSPacket = nil
			stream.videoSPSBytes = spsBytes
			stream.videoPPSBytes = ppsBytes
			return
		}
		if spsBytes > 0 {
			stream.videoSPSPacket = cloneRTPPacket(pkt)
			stream.videoSPSBytes = spsBytes
		}
		if ppsBytes > 0 {
			stream.videoPPSPacket = cloneRTPPacket(pkt)
			stream.videoPPSBytes = ppsBytes
		}
	}
}

func (stream *WebRTCStream) replayVideoParameterSets(
	localTrack *webrtc.TrackLocalStaticRTP,
	streamID string,
	timestamp uint32,
) bool {
	stream.mediaMu.RLock()
	paramPacket := cloneRTPPacket(stream.videoParamPacket)
	spsPacket := cloneRTPPacket(stream.videoSPSPacket)
	ppsPacket := cloneRTPPacket(stream.videoPPSPacket)
	spsBytes := stream.videoSPSBytes
	ppsBytes := stream.videoPPSBytes
	stream.mediaMu.RUnlock()

	if paramPacket != nil && spsBytes > 0 && ppsBytes > 0 {
		paramPacket.Timestamp = timestamp
		if err := stream.writeLocalTrack(localTrack, paramPacket); err != nil {
			log.Printf("[WHEP_PROXY] Failed replaying STAP-A SPS/PPS before IDR for %s: %v", streamID, err)
			return false
		}
		stream.videoPrimed.Store(true)
		if whepDebugEnabled() && stream.videoReplayLogged.CompareAndSwap(false, true) {
			log.Printf("[WHEP_PROXY] Replayed SPS (%d bytes) + PPS (%d bytes) before IDR for %s", spsBytes, ppsBytes, streamID)
		}
		stream.videoParamsMissed.Store(false)
		return true
	}

	if spsPacket == nil || ppsPacket == nil || spsBytes == 0 || ppsBytes == 0 {
		if stream.videoParamsMissed.CompareAndSwap(false, true) {
			log.Printf("[WHEP_PROXY] Missing buffered SPS/PPS before IDR for %s: sps=%d pps=%d", streamID, spsBytes, ppsBytes)
		}
		return false
	}

	spsPacket.Timestamp = timestamp
	ppsPacket.Timestamp = timestamp
	if err := stream.writeLocalTrack(localTrack, spsPacket); err != nil {
		log.Printf("[WHEP_PROXY] Failed replaying SPS before IDR for %s: %v", streamID, err)
		return false
	}
	if err := stream.writeLocalTrack(localTrack, ppsPacket); err != nil {
		log.Printf("[WHEP_PROXY] Failed replaying PPS before IDR for %s: %v", streamID, err)
		return false
	}

	stream.videoPrimed.Store(true)
	if whepDebugEnabled() && stream.videoReplayLogged.CompareAndSwap(false, true) {
		log.Printf("[WHEP_PROXY] Replayed SPS (%d bytes) + PPS (%d bytes) before IDR for %s", spsBytes, ppsBytes, streamID)
	}
	stream.videoParamsMissed.Store(false)
	return true
}

func (stream *WebRTCStream) shouldForwardVideoPacket(pkt *rtp.Packet) bool {
	if pkt == nil {
		return false
	}
	if stream.videoPrimed.Load() {
		return true
	}
	isIDR, _ := h264PacketInfo(pkt.Payload)
	if isIDR {
		stream.videoPrimed.Store(true)
		return true
	}
	return false
}

func (stream *WebRTCStream) writeLocalTrack(localTrack *webrtc.TrackLocalStaticRTP, pkt *rtp.Packet) error {
	if localTrack == nil || pkt == nil {
		return fmt.Errorf("local track or packet unavailable")
	}

	var mu *sync.Mutex
	switch localTrack {
	case stream.videoTrack:
		mu = &stream.videoTrackMu
	case stream.audioTrack:
		mu = &stream.audioTrackMu
	}

	if mu != nil {
		mu.Lock()
		defer mu.Unlock()

		// Keep downstream RTP sequence numbers monotonic per local track.
		switch localTrack {
		case stream.videoTrack:
			if !stream.videoOutSeqSet {
				stream.videoOutSeq = pkt.SequenceNumber
				stream.videoOutSeqSet = true
			} else {
				stream.videoOutSeq++
				pkt.SequenceNumber = stream.videoOutSeq
			}
		case stream.audioTrack:
			if !stream.audioOutSeqSet {
				stream.audioOutSeq = pkt.SequenceNumber
				stream.audioOutSeqSet = true
			} else {
				stream.audioOutSeq++
				pkt.SequenceNumber = stream.audioOutSeq
			}
		}
	}

	return localTrack.WriteRTP(pkt)
}

func forwardTrack(
	streamID string,
	stream *WebRTCStream,
	session *UpstreamSession,
	track *webrtc.TrackRemote,
	localTrack *webrtc.TrackLocalStaticRTP,
) {
	stream.forwardWg.Add(1)
	defer stream.forwardWg.Done()

	var readCount uint64
	var writtenCount uint64
	var droppedCount uint64
	var lastVideoSeq uint16
	var haveLastVideoSeq bool
	var fuActive bool

	for {
		pkt, _, err := track.ReadRTP()
		if err != nil {
			if whepDebugEnabled() || shouldLogTrackEnd(err) {
				log.Printf(
					"[WHEP_PROXY] Track ended for %s (%s): read=%d written=%d dropped=%d err=%v",
					streamID,
					track.Kind().String(),
					readCount,
					writtenCount,
					droppedCount,
					err,
				)
			}
			stream.handleUpstreamDisconnect(session, fmt.Sprintf("%s track ended: %v", track.Kind().String(), err))
			return
		}

		readCount++
		videoFUAEnded := false
		if track.Kind() == webrtc.RTPCodecTypeVideo {
			stream.bufferVideoParameterSet(pkt)
			isIDR, packetDesc := h264PacketInfo(pkt.Payload)
			isFUA, fuaStart, fuaEnd := h264FUAState(pkt.Payload)
			if isFUA {
				if haveLastVideoSeq && fuActive && pkt.SequenceNumber != lastVideoSeq+1 {
					fuActive = false
					if whepDebugEnabled() {
						log.Printf("[WHEP_PROXY] Dropping broken FU-A sequence for %s: expected seq=%d got=%d", streamID, lastVideoSeq+1, pkt.SequenceNumber)
					}
				}
				if fuaStart {
					fuActive = true
				} else if !fuActive {
					haveLastVideoSeq = true
					lastVideoSeq = pkt.SequenceNumber
					droppedCount++
					continue
				}
			} else {
				fuActive = false
			}
			videoFUAEnded = isFUA && fuaEnd
			if isIDR {
				if !stream.replayVideoParameterSets(localTrack, streamID, pkt.Timestamp) {
					droppedCount++
					continue
				}
				if whepDebugEnabled() && stream.videoIDRLogged.CompareAndSwap(false, true) {
					log.Printf(
						"[WHEP_PROXY] First IDR for %s: seq=%d marker=%t bytes=%d desc=%s",
						streamID,
						pkt.SequenceNumber,
						pkt.Marker,
						len(pkt.Payload),
						packetDesc,
					)
				}
			} else if !stream.shouldForwardVideoPacket(pkt) {
				droppedCount++
				continue
			}
			haveLastVideoSeq = true
			lastVideoSeq = pkt.SequenceNumber
		}
		if stream.whepClients.Load() == 0 {
			droppedCount++
		} else if err = stream.writeLocalTrack(localTrack, pkt); err != nil {
			droppedCount++
		} else {
			writtenCount++
			if track.Kind() == webrtc.RTPCodecTypeVideo && stream.videoPLIRequested.CompareAndSwap(true, false) {
				if pliErr := stream.requestVideoKeyframe("first downstream write"); pliErr != nil {
					log.Printf("[WHEP_PROXY] Failed to request keyframe for %s after first write: %v", streamID, pliErr)
					stream.videoPLIRequested.Store(true)
				}
			}
			if track.Kind() == webrtc.RTPCodecTypeVideo && videoFUAEnded {
				fuActive = false
			}
		}

		if whepDebugEnabled() && readCount%20000 == 0 {
			log.Printf(
				"[WHEP_PROXY] RTP stats for %s (%s): read=%d written=%d dropped=%d clients=%d",
				streamID,
				track.Kind().String(),
				readCount,
				writtenCount,
				droppedCount,
				stream.whepClients.Load(),
			)
		}
	}
}

func readReceiverRTCP(streamID string, track *webrtc.TrackRemote, receiver *webrtc.RTPReceiver) {
	for {
		pkts, _, err := receiver.ReadRTCP()
		if err != nil {
			if whepDebugEnabled() || shouldLogRTCPEnd(err) {
				log.Printf("[WHEP_PROXY] Receiver RTCP ended for %s (%s): %v", streamID, track.Kind().String(), err)
			}
			return
		}

		for _, pkt := range pkts {
			switch pkt.(type) {
			case *rtcp.PictureLossIndication, *rtcp.FullIntraRequest:
				if whepDebugEnabled() {
					log.Printf("[WHEP_PROXY] Upstream RTCP feedback for %s (%s): %T", streamID, track.Kind().String(), pkt)
				}
			}
		}
	}
}

func cleanupUpstreamLocked(stream *WebRTCStream) {
	current := stream.upstream
	stream.upstream = nil
	stream.upstreamAlive.Store(false)
	stream.resetUpstreamMediaState()
	closeUpstreamSession(current)
}

func cleanupUpstreamIfCurrent(stream *WebRTCStream, session *UpstreamSession) bool {
	if !stream.clearUpstreamIfCurrent(session) {
		return false
	}
	stream.resetUpstreamMediaState()
	closeUpstreamSession(session)
	return true
}

func destroyStreamLocked(streamID string, stream *WebRTCStream) {
	stream.destroyed.Store(true)
	cleanupUpstreamLocked(stream)
	delete(streams, streamID)
}

func destroyStream(streamID string, stream *WebRTCStream) {
	streamsMu.Lock()
	defer streamsMu.Unlock()
	destroyStreamLocked(streamID, stream)
}

func destroyStreamIfCurrent(streamID string, stream *WebRTCStream) {
	streamsMu.Lock()
	defer streamsMu.Unlock()
	if current, ok := streams[streamID]; ok && current == stream {
		destroyStreamLocked(streamID, stream)
	}
}

func (stream *WebRTCStream) scheduleReconnect(reason string) {
	if stream.destroyed.Load() {
		return
	}
	if !stream.reconnecting.CompareAndSwap(false, true) {
		return
	}

	go func() {
		stream.forwardWg.Wait()
		for attempt := 1; ; attempt++ {
			if stream.destroyed.Load() {
				stream.reconnecting.Store(false)
				return
			}

			delay := time.Duration(attempt*2) * time.Second
			if delay > 30*time.Second {
				delay = 30 * time.Second
			}
			log.Printf("[WHEP_PROXY] Reconnecting upstream for %s, attempt %d in %s (reason=%s)", stream.streamID, attempt, delay, reason)
			time.Sleep(delay)

			config, err := fetchKVSConfig(stream.streamID)
			if err != nil {
				log.Printf("[WHEP_PROXY] Failed to refresh KVS config for %s: %v", stream.streamID, err)
				continue
			}
			stream.setConfig(config)

			if err := establishUpstream(stream); err != nil {
				log.Printf("[WHEP_PROXY] Reconnect attempt %d failed for %s: %v", attempt, stream.streamID, err)
				continue
			}

			log.Printf("[WHEP_PROXY] Upstream reconnected for %s on attempt %d", stream.streamID, attempt)
			stream.reconnecting.Store(false)
			return
		}
	}()
}

func (stream *WebRTCStream) handleUpstreamDisconnect(session *UpstreamSession, reason string) {
	if stream.destroyed.Load() {
		return
	}
	if !cleanupUpstreamIfCurrent(stream, session) {
		return
	}
	if whepDebugEnabled() || !strings.Contains(reason, "websocket closed: websocket: close 1001") {
		log.Printf("[WHEP_PROXY] Upstream session ended for %s: %s", stream.streamID, reason)
	}
	stream.scheduleReconnect(reason)
}

func kvsConfigURL(streamID string) string {
	host := os.Getenv("KVS_CONFIG_HOST")
	if host == "" {
		host = "127.0.0.1"
	}
	port := os.Getenv("KVS_CONFIG_PORT")
	if port == "" {
		port = "5000"
	}
	return fmt.Sprintf("http://%s:%s/kvs-config/%s", host, port, streamID)
}

func fetchKVSConfig(streamID string) (WebRTCConfig, error) {
	var config WebRTCConfig
	if whepDebugEnabled() {
		log.Printf("[WHEP_PROXY] Fetching KVS config from %s", kvsConfigURL(streamID))
	}

	client := &http.Client{Timeout: 10 * time.Second}
	resp, err := client.Get(kvsConfigURL(streamID))
	if err != nil {
		return config, err
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		body, _ := io.ReadAll(io.LimitReader(resp.Body, 2048))
		return config, fmt.Errorf("refresh config status %d: %s", resp.StatusCode, strings.TrimSpace(string(body)))
	}

	if err := json.NewDecoder(resp.Body).Decode(&config); err != nil {
		return config, err
	}
	if config.SignalingURL == "" {
		return config, fmt.Errorf("refresh config missing signaling_url")
	}

	return config, nil
}

func isLoopbackRemoteAddr(remoteAddr string) bool {
	host, _, err := net.SplitHostPort(remoteAddr)
	if err != nil {
		host = remoteAddr
	}
	parsed := net.ParseIP(strings.TrimSpace(host))
	return parsed != nil && parsed.IsLoopback()
}

func main() {
	r := mux.NewRouter()
	r.HandleFunc("/whep/{streamID}", whepHandler).Methods("GET", "OPTIONS", "POST")
	r.HandleFunc("/websocket/{streamID}", websocketHandler).Methods("GET", "POST")
	r.HandleFunc("/status/{streamID}", statusHandler).Methods("GET")

	go func() {
		fmt.Println("[WHEP_PROXY] Listening on 127.0.0.1:8080")
		if err := http.ListenAndServe("127.0.0.1:8080", r); err != nil {
			panic(err)
		}
	}()

	sigchan := make(chan os.Signal, 1)
	signal.Notify(sigchan, os.Interrupt)
	<-sigchan

	fmt.Println("[WHEP_PROXY] Exiting.")

	streamsMu.Lock()
	defer streamsMu.Unlock()
	for streamID, stream := range streams {
		destroyStreamLocked(streamID, stream)
	}
}

func redactURL(raw string) string {
	parsed, err := url.Parse(raw)
	if err != nil {
		return raw
	}
	query := parsed.Query()
	for _, key := range []string{
		"X-Amz-Security-Token",
		"X-Amz-Signature",
		"X-Amz-Credential",
		"X-Amz-Date",
		"X-Amz-Expires",
	} {
		if query.Has(key) {
			query.Set(key, "REDACTED")
		}
	}
	parsed.RawQuery = query.Encode()
	return parsed.String()
}

func sendSignalingMessage(
	session *UpstreamSession,
	action string,
	payload interface{},
	correlationID string,
) error {
	encoded, err := json.Marshal(payload)
	if err != nil {
		return err
	}

	envelope := map[string]interface{}{
		"action":         action,
		"messagePayload": base64.StdEncoding.EncodeToString(encoded),
	}
	if session != nil && session.recipientClientID != "" {
		envelope["recipientClientId"] = session.recipientClientID
	}
	if correlationID != "" {
		envelope["correlationId"] = correlationID
	}

	session.wsMu.Lock()
	defer session.wsMu.Unlock()
	if session.wsConn == nil {
		return fmt.Errorf("websocket unavailable")
	}
	return session.wsConn.WriteJSON(envelope)
}

func decodeSignalingPayload(msg map[string]interface{}) ([]byte, error) {
	payload, _ := msg["messagePayload"].(string)
	if payload == "" {
		return nil, fmt.Errorf("empty messagePayload")
	}
	return base64.StdEncoding.DecodeString(payload)
}

func generateCorrelationID(phoneID string) string {
	correlationID := fmt.Sprintf("%s.%d", phoneID, time.Now().UnixMilli())
	if phoneID == "" {
		correlationID = fmt.Sprintf("%d", time.Now().UnixMilli())
	}
	if len(correlationID) <= 256 {
		return correlationID
	}
	return correlationID[len(correlationID)-256:]
}

func rewriteSessionLine(sdp, correlationID string) string {
	if correlationID == "" {
		return sdp
	}
	rewritten := strings.Replace(sdp, "s=-\r\n", "s="+correlationID+"\r\n", 1)
	if rewritten != sdp {
		return rewritten
	}
	return strings.Replace(sdp, "s=-\n", "s="+correlationID+"\n", 1)
}

func decodeSignalingURL(rawURL string) (string, error) {
	return rawURL, nil
}

func createPeerConnection(config WebRTCConfig) (*webrtc.PeerConnection, error) {
	iceServers := []webrtc.ICEServer{}
	for _, server := range config.ICEServers {
		iceServers = append(iceServers, webrtc.ICEServer{
			URLs:       []string{server.URL},
			Username:   server.Username,
			Credential: server.Credential,
		})
	}
	if len(iceServers) == 0 {
		iceServers = []webrtc.ICEServer{{URLs: []string{"stun:stun.l.google.com:19302"}}}
	}

	mediaEngine := &webrtc.MediaEngine{}
	if err := mediaEngine.RegisterDefaultCodecs(); err != nil {
		return nil, err
	}

	interceptorRegistry := &interceptor.Registry{}
	if err := webrtc.RegisterDefaultInterceptors(mediaEngine, interceptorRegistry); err != nil {
		return nil, err
	}

	return webrtc.NewAPI(
		webrtc.WithMediaEngine(mediaEngine),
		webrtc.WithInterceptorRegistry(interceptorRegistry),
	).NewPeerConnection(webrtc.Configuration{ICEServers: iceServers})
}

func handleRemoteAnswer(streamID string, session *UpstreamSession, msg map[string]interface{}) error {
	decoded, err := decodeSignalingPayload(msg)
	if err != nil {
		return err
	}

	var answer webrtc.SessionDescription
	if err := json.Unmarshal(decoded, &answer); err != nil {
		return fmt.Errorf("unmarshal SDP_ANSWER: %w", err)
	}

	if whepDebugEnabled() {
		fmt.Println("[WHEP_PROXY] Received SDP_ANSWER for", streamID)
	}
	answer.SDP = strings.ReplaceAll(answer.SDP, "\\r\\n", "\r\n")
	if err := session.peerConnection.SetRemoteDescription(answer); err != nil {
		return fmt.Errorf("set remote description: %w", err)
	}
	session.remoteDescription = &answer

	for _, candidate := range session.pendingCandidates {
		if err := session.peerConnection.AddICECandidate(candidate); err != nil {
			fmt.Println("[WHEP_PROXY] Failed to add queued ICE candidate:", err)
		}
	}
	session.pendingCandidates = nil
	return nil
}

func handleRemoteCandidate(streamID string, session *UpstreamSession, msg map[string]interface{}) error {
	decoded, err := decodeSignalingPayload(msg)
	if err != nil {
		return err
	}

	var candidateMap map[string]interface{}
	if err := json.Unmarshal(decoded, &candidateMap); err != nil {
		return fmt.Errorf("unmarshal ICE_CANDIDATE: %w", err)
	}

	candidateString, ok := candidateMap["candidate"].(string)
	if !ok || candidateString == "" {
		return fmt.Errorf("candidate string missing")
	}

	candidate := webrtc.ICECandidateInit{Candidate: candidateString}
	if sdpMid, ok := candidateMap["sdpMid"].(string); ok && sdpMid != "" {
		candidate.SDPMid = &sdpMid
	}
	if mLineIndex, ok := candidateMap["sdpMLineIndex"].(float64); ok {
		uint16Val := uint16(mLineIndex)
		candidate.SDPMLineIndex = &uint16Val
	}

	if session.remoteDescription == nil {
		session.pendingCandidates = append(session.pendingCandidates, candidate)
		fmt.Println("[WHEP_PROXY] Queued ICE_CANDIDATE for", streamID)
		return nil
	}

	fmt.Println("[WHEP_PROXY] Received ICE_CANDIDATE for", streamID)
	return session.peerConnection.AddICECandidate(candidate)
}

func createAndSendOffer(streamID string, session *UpstreamSession) error {
	offer, err := session.peerConnection.CreateOffer(nil)
	if err != nil {
		return fmt.Errorf("create offer: %w", err)
	}
	if err := session.peerConnection.SetLocalDescription(offer); err != nil {
		return fmt.Errorf("set local description: %w", err)
	}

	// Wait for ICE gathering to complete so the offer SDP includes local candidates.
	// Some KVS/camera implementations expect at least one candidate before responding.
	gatherComplete := webrtc.GatheringCompletePromise(session.peerConnection)
	select {
	case <-gatherComplete:
		// done
	case <-time.After(10 * time.Second):
		fmt.Println("[WHEP_PROXY] ICE gathering timeout for", streamID, "; sending offer anyway")
	}

	localDescription := session.peerConnection.LocalDescription()
	if localDescription == nil {
		return fmt.Errorf("local description unavailable after SetLocalDescription")
	}

	envelope := map[string]interface{}{
		"type": "offer",
		"sdp":  rewriteSessionLine(localDescription.SDP, session.correlationID),
	}
	if whepDebugEnabled() {
		if decoded, err := json.Marshal(envelope); err == nil {
			fmt.Println("[WHEP_PROXY] SDP_OFFER payload for", streamID, string(decoded))
		}
		if payload, err := json.Marshal(map[string]interface{}{
			"action":         "SDP_OFFER",
			"messagePayload": base64.StdEncoding.EncodeToString(mustJSON(envelope)),
			"correlationId":  session.correlationID,
		}); err == nil {
			fmt.Println("[WHEP_PROXY] Sending envelope for", streamID, string(payload))
		}
	}
	return sendSignalingMessage(session, "SDP_OFFER", envelope, session.correlationID)
}

func establishUpstream(stream *WebRTCStream) error {
	config := stream.getConfig()
	decodedURL, err := decodeSignalingURL(config.SignalingURL)
	if err != nil {
		return fmt.Errorf("decode signaling URL: %w", err)
	}

	if whepDebugEnabled() {
		fmt.Println("[WHEP_PROXY] Connecting websocket:", redactURL(decodedURL))
	}

	dialer := *websocket.DefaultDialer
	dialer.HandshakeTimeout = 20 * time.Second
	dialer.EnableCompression = true
	headers := http.Header{
		"User-Agent": {"okhttp/4.12.0"},
	}
	conn, resp, err := dialer.Dial(decodedURL, headers)
	if err != nil {
		if resp != nil {
			if resp.Body != nil {
				defer resp.Body.Close()
			}
			fmt.Println("[WHEP_PROXY] Websocket handshake status:", resp.Status)
			fmt.Println("[WHEP_PROXY] Websocket handshake headers:", resp.Header)
		}
		if resp != nil && resp.Body != nil {
			bodyBytes := make([]byte, 2048)
			if n, readErr := resp.Body.Read(bodyBytes); readErr == nil || readErr == io.EOF {
				fmt.Println("[WHEP_PROXY] Websocket response:", string(bodyBytes[:n]))
			}
		}
		return fmt.Errorf("connect websocket: %w", err)
	}

	peerConnection, err := createPeerConnection(config)
	if err != nil {
		_ = conn.Close()
		return err
	}

	session := &UpstreamSession{
		peerConnection: peerConnection,
		wsConn:         conn,
		correlationID:  generateCorrelationID(config.PhoneID),
		recipientClientID: config.PhoneID,
		startedAt:      time.Now(),
	}
	stream.setUpstream(session)
	traceLogf(stream.streamID, "upstream connect start signaling=%s", sanitizeLogURL(config.SignalingURL))

	if _, err = peerConnection.AddTransceiverFromKind(
		webrtc.RTPCodecTypeVideo,
		webrtc.RTPTransceiverInit{Direction: webrtc.RTPTransceiverDirectionRecvonly},
	); err != nil {
		stream.handleUpstreamDisconnect(session, fmt.Sprintf("add video transceiver: %v", err))
		return err
	}

	if _, err = peerConnection.AddTransceiverFromKind(
		webrtc.RTPCodecTypeAudio,
		webrtc.RTPTransceiverInit{Direction: webrtc.RTPTransceiverDirectionRecvonly},
	); err != nil {
		stream.handleUpstreamDisconnect(session, fmt.Sprintf("add audio transceiver: %v", err))
		return err
	}

	peerConnection.OnICEConnectionStateChange(func(state webrtc.ICEConnectionState) {
		if whepDebugEnabled() || state == webrtc.ICEConnectionStateFailed || state == webrtc.ICEConnectionStateDisconnected {
			log.Printf("[WHEP_PROXY] ICE connection state for %s: %s", stream.streamID, state.String())
		}
		traceLogf(stream.streamID, "upstream ice state=%s after=%s", state.String(), time.Since(session.startedAt).Round(time.Millisecond))
	})
	peerConnection.OnConnectionStateChange(func(state webrtc.PeerConnectionState) {
		if whepDebugEnabled() || state == webrtc.PeerConnectionStateFailed || state == webrtc.PeerConnectionStateDisconnected {
			log.Printf("[WHEP_PROXY] Peer connection state for %s: %s", stream.streamID, state.String())
		}
		traceLogf(stream.streamID, "upstream peer state=%s after=%s", state.String(), time.Since(session.startedAt).Round(time.Millisecond))
		switch state {
		case webrtc.PeerConnectionStateFailed, webrtc.PeerConnectionStateClosed:
			stream.handleUpstreamDisconnect(session, fmt.Sprintf("peer connection state=%s", state.String()))
		}
	})

	peerConnection.OnICECandidate(func(c *webrtc.ICECandidate) {
		if c == nil {
			return
		}
		candidate := c.ToJSON()
		if err := sendSignalingMessage(session, "ICE_CANDIDATE", candidate, session.correlationID); err != nil {
			fmt.Println("[WHEP_PROXY] Error sending ICE candidate:", err)
		}
	})

	peerConnection.OnTrack(func(track *webrtc.TrackRemote, receiver *webrtc.RTPReceiver) {
		if stream.currentUpstream() != session {
			return
		}

		if whepDebugEnabled() {
			log.Printf("[WHEP_PROXY] Received track for %s: codec=%s", stream.streamID, track.Codec().MimeType)
			fmt.Printf(
				"[WHEP_PROXY] Received remote track for %s: kind=%s codec=%s payloadType=%d\n",
				stream.streamID,
				track.Kind().String(),
				track.Codec().MimeType,
				track.PayloadType(),
			)
		}

		var localTrack *webrtc.TrackLocalStaticRTP
		switch track.Kind() {
		case webrtc.RTPCodecTypeVideo:
			stream.setVideoSource(track)
			localTrack = stream.videoTrack
			if session.videoTrackLogged.CompareAndSwap(false, true) {
				traceLogf(stream.streamID, "first upstream video track codec=%s payload=%d after=%s", track.Codec().MimeType, track.PayloadType(), time.Since(session.startedAt).Round(time.Millisecond))
			}
			if stream.whepClients.Load() > 0 {
				stream.videoPLIRequested.Store(true)
				if err := stream.requestVideoKeyframe("upstream track available"); err != nil {
					log.Printf("[WHEP_PROXY] Failed to request keyframe for %s on upstream track: %v", stream.streamID, err)
				}
			}
		case webrtc.RTPCodecTypeAudio:
			stream.setAudioReady(true)
			localTrack = stream.audioTrack
			if session.audioTrackLogged.CompareAndSwap(false, true) {
				traceLogf(stream.streamID, "first upstream audio track codec=%s payload=%d after=%s", track.Codec().MimeType, track.PayloadType(), time.Since(session.startedAt).Round(time.Millisecond))
			}
		default:
			return
		}

		go readReceiverRTCP(stream.streamID, track, receiver)
		go forwardTrack(stream.streamID, stream, session, track, localTrack)

		if track.Kind() == webrtc.RTPCodecTypeVideo {
			go func() {
				ticker := time.NewTicker(60 * time.Second)
				defer ticker.Stop()

				for range ticker.C {
					if stream.currentUpstream() != session || session.peerConnection == nil || session.peerConnection.ConnectionState() == webrtc.PeerConnectionStateClosed {
						return
					}
					if stream.whepClients.Load() == 0 {
						continue
					}
					if err := stream.requestVideoKeyframe("periodic downstream refresh"); err != nil {
						log.Printf("[WHEP_PROXY] Failed to request keyframe for %s: %v", stream.streamID, err)
						return
					}
				}
			}()
		}
	})

	go func() {
		for {
			messageType, data, err := conn.ReadMessage()
			if err != nil {
				closeInfo := classifyWSReadError(err)
				state := webrtc.PeerConnectionStateClosed
				iceState := webrtc.ICEConnectionStateClosed
				if session.peerConnection != nil {
					state = session.peerConnection.ConnectionState()
					iceState = session.peerConnection.ICEConnectionState()
				}
				videoReady := stream.videoReady.Load()
				audioReady := stream.audioReady.Load()
				upstreamAlive := stream.upstreamAlive.Load()
				whepClients := stream.whepClients.Load()
				if closeInfo.normal {
					logNormalClose(session, stream.streamID, closeInfo, state, iceState, videoReady, audioReady, upstreamAlive, whepClients)
					if !shouldReconnectOnNormalWSClosure(state, videoReady, audioReady) {
						log.Printf(
							"[WHEP_PROXY] Keeping upstream peer alive for %s after normal websocket close: peer=%s video_ready=%t audio_ready=%t",
							stream.streamID,
							state.String(),
							videoReady,
							audioReady,
						)
						closeNormalRotationWebsocket(session)
						return
					}
				} else if closeInfo.code != 0 {
					log.Printf("[WHEP_PROXY] Websocket closed by peer for %s: code=%d reason=%q", stream.streamID, closeInfo.code, closeInfo.reason)
				} else if !errors.Is(err, io.EOF) {
					log.Printf("[WHEP_PROXY] Error reading websocket message for %s: %v", stream.streamID, err)
				} else if whepDebugEnabled() {
					log.Printf("[WHEP_PROXY] Websocket read EOF for %s", stream.streamID)
				}
				stream.handleUpstreamDisconnect(session, fmt.Sprintf("websocket closed: %v", err))
				return
			}

			if len(data) == 0 {
				if whepDebugEnabled() {
					log.Println("[WHEP_PROXY] Skipping empty keepalive frame")
				}
				continue
			}

			if whepDebugEnabled() {
				const rawLogLen = 200
				msgTypeStr := "other"
				switch messageType {
				case websocket.TextMessage:
					msgTypeStr = "text"
				case websocket.BinaryMessage:
					msgTypeStr = "binary"
				}
				sampleLen := len(data)
				if sampleLen > rawLogLen {
					sampleLen = rawLogLen
				}
				if messageType == websocket.BinaryMessage && sampleLen > 0 {
					fmt.Printf("[WHEP_PROXY] raw message type=%s len=%d first%d_hex=%s\n", msgTypeStr, len(data), sampleLen, hex.EncodeToString(data[:sampleLen]))
				} else if sampleLen > 0 {
					payload := string(data[:sampleLen])
					if strings.ContainsAny(payload, "\r\n") {
						payload = strings.ReplaceAll(strings.ReplaceAll(payload, "\r", "\\r"), "\n", "\\n")
					}
					fmt.Printf("[WHEP_PROXY] raw message type=%s len=%d first%d=%s\n", msgTypeStr, len(data), sampleLen, payload)
				} else {
					fmt.Printf("[WHEP_PROXY] raw message type=%s len=0\n", msgTypeStr)
				}
			}

			var jsonData []byte
			switch messageType {
			case websocket.TextMessage:
				jsonData = data
			case websocket.BinaryMessage:
				if jsonErr := json.Unmarshal(data, &(map[string]interface{}{})); jsonErr == nil {
					jsonData = data
				} else {
					decoded, decErr := base64.StdEncoding.DecodeString(string(data))
					if decErr != nil {
						fmt.Printf("[WHEP_PROXY] Binary message: not valid JSON (%v) and base64 decode failed: %v\n", jsonErr, decErr)
						continue
					}
					jsonData = decoded
				}
			default:
				fmt.Printf("[WHEP_PROXY] Ignoring websocket message type %d\n", messageType)
				continue
			}

			var msg map[string]interface{}
			if err := json.Unmarshal(jsonData, &msg); err != nil {
				fmt.Println("[WHEP_PROXY] Error unmarshaling signaling JSON:", err)
				continue
			}

			msgType, _ := msg["messageType"].(string)
			if msgType == "" {
				msgType, _ = msg["action"].(string)
			}
			if msgType == "" {
				fmt.Println("[WHEP_PROXY] Ignoring signaling message without type:", msg)
				continue
			}

			if correlationID, _ := msg["correlationId"].(string); correlationID != "" && correlationID != session.correlationID {
				fmt.Printf("[WHEP_PROXY] Ignoring %s for %s due to mismatched correlationId %q\n", msgType, stream.streamID, correlationID)
				continue
			}

			switch msgType {
			case "SDP_ANSWER":
				if err := handleRemoteAnswer(stream.streamID, session, msg); err != nil {
					fmt.Println("[WHEP_PROXY] Failed to handle SDP_ANSWER:", err)
				}
			case "ICE_CANDIDATE":
				if err := handleRemoteCandidate(stream.streamID, session, msg); err != nil {
					fmt.Println("[WHEP_PROXY] Failed to handle ICE_CANDIDATE:", err)
				}
			case "STATUS_RESPONSE":
				fmt.Println("[WHEP_PROXY] Received STATUS_RESPONSE for", stream.streamID, msg)
			default:
				fmt.Println("[WHEP_PROXY] Ignoring signaling message type:", msgType)
			}
		}
	}()

	if delayMs := os.Getenv("WHEP_SIGNALING_DELAY_MS"); delayMs != "" {
		if ms, err := strconv.Atoi(delayMs); err == nil && ms > 0 {
			d := time.Duration(ms) * time.Millisecond
			fmt.Printf("[WHEP_PROXY] Waiting %v before sending SDP_OFFER for %s\n", d, stream.streamID)
			time.Sleep(d)
		}
	}
	if err := createAndSendOffer(stream.streamID, session); err != nil {
		stream.handleUpstreamDisconnect(session, fmt.Sprintf("createAndSendOffer failed: %v", err))
		return err
	}

	return nil
}

func websocketHandler(w http.ResponseWriter, r *http.Request) {
	if !isLoopbackRemoteAddr(r.RemoteAddr) {
		http.Error(w, "Forbidden", http.StatusForbidden)
		return
	}

	if r.Method != http.MethodPost {
		http.Error(w, "Method not allowed", http.StatusMethodNotAllowed)
		return
	}

	streamID := mux.Vars(r)["streamID"]

	var config WebRTCConfig
	var stream *WebRTCStream
	if err := json.NewDecoder(r.Body).Decode(&config); err != nil {
		http.Error(w, "Invalid JSON configuration", http.StatusBadRequest)
		return
	}
	if config.SignalingURL == "" {
		http.Error(w, "Signaling URL is required", http.StatusBadRequest)
		return
	}
	// If we already have an active proxy for this stream (e.g. duplicate POST from setup_streams + runOnInit),
	// do not replace it — return 200 so the first session stays alive for ICE/media.
	streamsMu.Lock()
	if existing := streams[streamID]; existing != nil {
		if !existing.canReuse() {
			fmt.Println("[WHEP_PROXY] Existing stream is stale; replacing", streamID)
			destroyStreamLocked(streamID, existing)
		} else {
			existing.setConfig(config)
			streamsMu.Unlock()
			w.Header().Set("Content-Type", "application/json")
			w.WriteHeader(http.StatusOK)
			_, _ = w.Write([]byte(`{"status":"ok","reused":true}`))
			return
		}
	}

	videoTrack, err := webrtc.NewTrackLocalStaticRTP(
		webrtc.RTPCodecCapability{MimeType: webrtc.MimeTypeH264},
		"video",
		"pion",
	)
	if err != nil {
		streamsMu.Unlock()
		http.Error(w, err.Error(), http.StatusInternalServerError)
		return
	}

	audioTrack, err := webrtc.NewTrackLocalStaticRTP(
		webrtc.RTPCodecCapability{
			MimeType:  webrtc.MimeTypePCMU,
			ClockRate: 8000,
			Channels:  2,
		},
		"audio",
		"pion",
	)
	if err != nil {
		streamsMu.Unlock()
		http.Error(w, err.Error(), http.StatusInternalServerError)
		return
	}

	stream = &WebRTCStream{
		streamID:   streamID,
		videoTrack: videoTrack,
		audioTrack: audioTrack,
	}
	stream.setConfig(config)
	streams[streamID] = stream
	streamsMu.Unlock()

	// Respond 200 immediately so the client (Python) does not time out and retry. The client uses
	// a 10s timeout; delay + ICE gathering + offer can exceed that and cause a second POST, which
	// would replace this stream and close the websocket before ICE/media establish.
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(http.StatusOK)
	_, _ = w.Write([]byte(`{"status":"ok"}`))

	go func(stream *WebRTCStream) {
		if err := establishUpstream(stream); err != nil {
			log.Printf("[WHEP_PROXY] Initial upstream establish failed for %s: %v", stream.streamID, err)
			stream.scheduleReconnect("initial establish failed")
		}
	}(stream)
}

func statusHandler(w http.ResponseWriter, r *http.Request) {
	if !isLoopbackRemoteAddr(r.RemoteAddr) {
		http.Error(w, "Forbidden", http.StatusForbidden)
		return
	}

	streamID := mux.Vars(r)["streamID"]

	streamsMu.Lock()
	stream, ok := streams[streamID]
	streamsMu.Unlock()
	if !ok {
		http.Error(w, fmt.Sprintf("Stream %s not found", streamID), http.StatusNotFound)
		return
	}

	w.Header().Set("Content-Type", "application/json")
	if err := json.NewEncoder(w).Encode(stream.status()); err != nil {
		http.Error(w, "Error encoding status", http.StatusInternalServerError)
	}
}

func mustJSON(v interface{}) []byte {
	data, err := json.Marshal(v)
	if err != nil {
		panic(err)
	}
	return data
}

func whepDebugEnabled() bool {
	v := strings.TrimSpace(strings.ToLower(os.Getenv("WHEP_DEBUG")))
	return v == "1" || v == "true" || v == "yes" || v == "on"
}

func whepTraceStream() string {
	return strings.TrimSpace(strings.ToLower(os.Getenv("WHEP_TRACE_STREAM")))
}

func whepTraceEnabled(streamID string) bool {
	traceStream := whepTraceStream()
	return traceStream != "" && strings.EqualFold(traceStream, streamID)
}

func traceLogf(streamID, format string, args ...interface{}) {
	if !whepTraceEnabled(streamID) {
		return
	}
	log.Printf("[WHEP_TRACE] %s: %s", streamID, fmt.Sprintf(format, args...))
}

func sanitizeLogURL(raw string) string {
	parsed, err := url.Parse(raw)
	if err != nil || parsed.Scheme == "" || parsed.Host == "" {
		return "<redacted>"
	}
	return fmt.Sprintf("%s://%s%s", parsed.Scheme, parsed.Host, parsed.Path)
}

func sdpHasMediaLine(sdp, media string) bool {
	return strings.Contains(sdp, "\nm="+media+" ") || strings.HasPrefix(sdp, "m="+media+" ")
}

func whepHandler(w http.ResponseWriter, r *http.Request) {
	if !isLoopbackRemoteAddr(r.RemoteAddr) {
		http.Error(w, "Forbidden", http.StatusForbidden)
		return
	}

	streamID := mux.Vars(r)["streamID"]

	streamsMu.Lock()
	stream, ok := streams[streamID]
	streamsMu.Unlock()
	if !ok {
		http.Error(w, fmt.Sprintf("Stream %s not found", streamID), http.StatusNotFound)
		return
	}

	switch r.Method {
	case http.MethodOptions, http.MethodGet:
		w.Header().Set("Content-Type", "application/sdp")
		fmt.Fprint(w, "")
	case http.MethodPost:
		if !strings.HasPrefix(r.Header.Get("Content-Type"), "application/sdp") {
			http.Error(w, "Content-Type must be application/sdp", http.StatusUnsupportedMediaType)
			return
		}

		log.Printf("[WHEP_PROXY] WHEP offer received for %s from %s", streamID, r.RemoteAddr)

		body, err := io.ReadAll(r.Body)
		if err != nil {
			http.Error(w, "Error reading request body", http.StatusBadRequest)
			return
		}
		offerSDP := string(body)
		log.Printf(
			"[WHEP_PROXY] WHEP offer for %s: video=%t audio=%t",
			streamID,
			sdpHasMediaLine(offerSDP, "video"),
			sdpHasMediaLine(offerSDP, "audio"),
		)

		peerConnection, err := createPeerConnection(WebRTCConfig{})
		if err != nil {
			http.Error(w, "Error creating peer connection", http.StatusInternalServerError)
			return
		}

		tracks := stream.outputTracks()
		if len(tracks) == 0 {
			_ = peerConnection.Close()
			http.Error(w, "Stream has no output tracks", http.StatusServiceUnavailable)
			return
		}

		var countedClient atomic.Bool
		peerConnection.OnConnectionStateChange(func(state webrtc.PeerConnectionState) {
			if whepDebugEnabled() || state == webrtc.PeerConnectionStateFailed || state == webrtc.PeerConnectionStateDisconnected || state == webrtc.PeerConnectionStateClosed {
				log.Printf("[WHEP_PROXY] Downstream WHEP peer for %s: state=%s", streamID, state.String())
			}
			switch state {
			case webrtc.PeerConnectionStateConnected:
				if countedClient.CompareAndSwap(false, true) {
					stream.whepClients.Add(1)
					stream.videoPLIRequested.Store(true)
				}
				if err := stream.requestVideoKeyframe("downstream connected"); err != nil {
					log.Printf("[WHEP_PROXY] Failed to request keyframe for %s on connect: %v", streamID, err)
				}
			case webrtc.PeerConnectionStateDisconnected, webrtc.PeerConnectionStateFailed, webrtc.PeerConnectionStateClosed:
				if countedClient.CompareAndSwap(true, false) {
					stream.whepClients.Add(-1)
					if stream.whepClients.Load() == 0 {
						stream.videoPLIRequested.Store(false)
					}
				}
				if state == webrtc.PeerConnectionStateFailed || state == webrtc.PeerConnectionStateClosed {
					_ = peerConnection.Close()
				}
			}
		})

		if err = peerConnection.SetRemoteDescription(webrtc.SessionDescription{
			Type: webrtc.SDPTypeOffer,
			SDP:  offerSDP,
		}); err != nil {
			_ = peerConnection.Close()
			http.Error(w, "Error setting remote description", http.StatusInternalServerError)
			return
		}

		videoAdded := false
		audioAdded := false
		for _, track := range tracks {
			rtpSender, addTrackErr := peerConnection.AddTrack(track)
			if addTrackErr != nil {
				_ = peerConnection.Close()
				http.Error(w, "Error adding track", http.StatusInternalServerError)
				return
			}
			switch strings.ToLower(track.Codec().MimeType) {
			case strings.ToLower(webrtc.MimeTypeH264):
				videoAdded = true
			case strings.ToLower(webrtc.MimeTypePCMU):
				audioAdded = true
			}

			go func(sender *webrtc.RTPSender) {
				rtcpBuf := make([]byte, 1500)
				for {
					n, _, rtcpErr := sender.Read(rtcpBuf)
					if rtcpErr != nil {
						return
					}

					packets, unmarshalErr := rtcp.Unmarshal(rtcpBuf[:n])
					if unmarshalErr != nil {
						continue
					}
					for _, pkt := range packets {
						switch pkt.(type) {
						case *rtcp.PictureLossIndication, *rtcp.FullIntraRequest:
							if err := stream.requestVideoKeyframe("downstream rtcp feedback"); err != nil {
								log.Printf("[WHEP_PROXY] Failed to forward keyframe request for %s: %v", streamID, err)
							}
						}
					}
				}
			}(rtpSender)
		}
		if whepDebugEnabled() {
			log.Printf("[WHEP_PROXY] WHEP tracks added for %s: video=%v audio=%v", streamID, videoAdded, audioAdded)
		}

		gatherComplete := webrtc.GatheringCompletePromise(peerConnection)
		answer, err := peerConnection.CreateAnswer(&webrtc.AnswerOptions{})
		if err != nil {
			_ = peerConnection.Close()
			http.Error(w, "Error creating SDP answer", http.StatusInternalServerError)
			return
		}
		if err = peerConnection.SetLocalDescription(answer); err != nil {
			_ = peerConnection.Close()
			http.Error(w, "Error setting local description", http.StatusInternalServerError)
			return
		}

		etag := stream.ensureETag()
		<-gatherComplete
		localDescription := peerConnection.LocalDescription()
		if localDescription == nil {
			_ = peerConnection.Close()
			http.Error(w, "Local description unavailable", http.StatusInternalServerError)
			return
		}
		log.Printf(
			"[WHEP_PROXY] WHEP answer for %s: video=%t audio=%t",
			streamID,
			sdpHasMediaLine(localDescription.SDP, "video"),
			sdpHasMediaLine(localDescription.SDP, "audio"),
		)

		w.Header().Set("Content-Type", "application/sdp")
		w.Header().Set("Location", fmt.Sprintf("/whep/%s", streamID))
		w.Header().Set("ETag", etag)
		w.WriteHeader(http.StatusCreated)
		fmt.Fprint(w, localDescription.SDP)
	default:
		http.Error(w, "Method not allowed", http.StatusMethodNotAllowed)
	}
}

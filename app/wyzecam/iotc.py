import atexit
import base64
import contextlib
import enum
import errno
import hashlib
import json
import logging
import os
import pathlib
import threading
import time
import warnings
from ctypes import CDLL, c_int, c_ubyte, c_uint16, c_uint, c_uint32
from typing import Callable, Iterator, Optional, Tuple, Union

from wyzebridge.config import CONNECT_TIMEOUT, FORCE_IOTC_DETAIL, LLHLS, SDK_KEY
from wyzecam.api_models import WyzeAccount, WyzeCamera
from wyzecam.tutk import tutk, tutk_ioctl_mux, tutk_protocol
from wyzecam.tutk.tutk_ioctl_mux import TutkIOCtrlMux
from wyzecam.tutk.tutk_protocol import (
    K10000ConnectRequest,
    K10052DBSetResolvingBit,
    K10056SetResolvingBit,
    respond_to_ioctrl_10001,
)

logger = logging.getLogger(__name__)


def _hl_cam4_main_probe_mode() -> str:
    mode = os.getenv("HL_CAM4_MAIN_PROBE_MODE", "kvs").strip().lower()
    return mode if mode in {"kvs", "tutk_dtls", "tutk_parallel"} else "kvs"


def _tutk_trace_enabled(camera: WyzeCamera) -> bool:
    raw = os.getenv("TUTK_TRACE_STREAM", "").strip().lower()
    if not raw:
        return False

    targets = {item.strip() for item in raw.split(",") if item.strip()}
    return "all" in targets or camera.name_uri in targets


def _log_tutk_trace(camera: WyzeCamera, event: str, **fields) -> None:
    raw = os.getenv("TUTK_TRACE_STREAM", "").strip().lower()
    enabled = _tutk_trace_enabled(camera)
    if event == "connect_start":
        print(
            f"[TUTK_TRACE_GATE] raw={raw!r} camera={camera.name_uri} enabled={enabled}",
            flush=True,
        )
    if not enabled:
        return

    payload = {"camera": camera.name_uri, "event": event} | fields
    trace = f"[TUTK_TRACE] {json.dumps(payload, sort_keys=True)}"
    logger.info(trace)
    print(trace, flush=True)


def _hl_cam4_connect_watchdog_secs() -> Optional[float]:
    raw = os.getenv("HL_CAM4_CONNECT_WATCHDOG_SECS", "").strip().lower()
    if raw in {"0", "false", "no", "off"}:
        return None
    if raw:
        try:
            return max(float(raw), 0.1)
        except ValueError:
            logger.warning(
                "[IOTC] Ignoring invalid HL_CAM4_CONNECT_WATCHDOG_SECS=%r", raw
            )
            return None
    return float(CONNECT_TIMEOUT + 2)


def _truthy_env(name: str) -> bool:
    return os.getenv(name, "").strip().lower() in {"1", "true", "yes", "on"}


def _configure_tutk_native_log(tutk_platform_lib: CDLL) -> None:
    if not _truthy_env("TUTK_NATIVE_LOG"):
        return

    log_path = (
        os.getenv("TUTK_NATIVE_LOG_PATH", "/tmp/tutk_iotc.log").strip()
        or "/tmp/tutk_iotc.log"
    )
    level_raw = os.getenv("TUTK_NATIVE_LOG_LEVEL", "0").strip()
    try:
        log_level = max(int(level_raw), 0)
    except ValueError:
        logger.warning("[TUTK] Ignoring invalid TUTK_NATIVE_LOG_LEVEL=%r", level_raw)
        log_level = 0

    try:
        pathlib.Path(log_path).parent.mkdir(parents=True, exist_ok=True)
    except OSError as ex:
        print(
            f"[TUTK_NATIVE_LOG] mkdir_failed path={log_path} error={type(ex).__name__}: {ex}",
            flush=True,
        )

    errno = tutk.iotc_set_log_attr(
        tutk_platform_lib,
        log_path,
        c_uint32(log_level),
    )
    print(
        f"[TUTK_NATIVE_LOG] path={log_path} level={log_level} errno={errno}",
        flush=True,
    )


class WyzeIOTC:
    """Wyze IOTC singleton, used to construct iotc_sessions.

    This object should generally be used inside a context manager, i.e.:

    ```python
    with WyzeIOTC() as wyze:
        with wyze.connect_and_auth(account, camera) as session:
            ...  # send commands to the camera, then start streaming
    ```

    :var tutk_platform_lib: the underlying c library used to communicate with the wyze
                            device; see [wyzecam.tutk.tutk.load_library][]
    :var udp_port: the UDP port used on this machine for communication with wyze cameras on the same network
    :vartype udp_port: int
    :var max_num_av_channels: the maximum number of simultaneous sessions this object supports.
    :vartype max_num_av_channels: c_int
    :var version: the version of the underyling `tutk_platform_lib`
    """

    def __init__(
        self,
        tutk_platform_lib: Optional[Union[str, CDLL]] = None,
        udp_port: Optional[c_uint16] = None,
        max_num_av_channels: Optional[c_int] = None,
        sdk_key: Optional[str] = None,
    ) -> None:
        """Construct a WyzeIOTC session object.

        You should only create one of these at a time.

        :param tutk_platform_lib: The underlying c library (from tutk.load_library()), or the path
                                  to this library.
        :param udp_port: Specify a UDP port. Random UDP port is used if it is specified as 0.
        :param max_num_av_channels: The max number of AV channels. If it is specified
                                    less than 1, AV will set max number of AV channels as 1.

        """
        if FORCE_IOTC_DETAIL:
            logging.basicConfig()
            logger.setLevel(logging.DEBUG)
            tutk_protocol.logger.setLevel(logging.DEBUG)
            tutk_ioctl_mux.logger.setLevel(logging.DEBUG)

        if tutk_platform_lib is None:
            tutk_platform_lib = tutk.load_library()

        if isinstance(tutk_platform_lib, str):
            path = pathlib.Path(tutk_platform_lib)
            tutk_platform_lib = tutk.load_library(str(path.absolute()))

        _configure_tutk_native_log(tutk_platform_lib)

        if not sdk_key:
            sdk_key = SDK_KEY

        license_status = tutk.TUTK_SDK_Set_License_Key(tutk_platform_lib, str(sdk_key))
        if license_status < 0:
            raise tutk.TutkError(license_status)

        set_region = tutk_platform_lib.TUTK_SDK_Set_Region(3)  # REGION_US
        if set_region < 0:
            raise tutk.TutkError(set_region)

        self.tutk_platform_lib: CDLL = tutk_platform_lib
        self.initd = False
        self.udp_port = udp_port
        self.max_num_av_channels = max_num_av_channels
        self.sdk_key = sdk_key

    def initialize(self):
        """Initialize the underlying TUTK library.

        This is called automatically by the context manager,
        and should only be called if you intend to manually handle
        cleanup of this classes resources (by calling deinitialize
        when done with it!)
        """
        if self.initd:
            print("[DEBUG-IOTC] TUTK already initialized, skipping", flush=True)
            return

        print("[DEBUG-IOTC] Initializing TUTK library...", flush=True)
        self.initd = True

        print("[DEBUG-IOTC] Calling iotc_initialize...", flush=True)
        err_no = tutk.iotc_initialize(
            self.tutk_platform_lib, udp_port=self.udp_port or c_uint16(0)
        )
        print(f"[DEBUG-IOTC] iotc_initialize returned: {err_no}", flush=True)
        if err_no < 0:
            print(f"[DEBUG-IOTC] iotc_initialize FAILED: {err_no}", flush=True)
            raise tutk.TutkError(err_no)

        print("[DEBUG-IOTC] Calling av_initialize...", flush=True)
        actual_num_chans = tutk.av_initialize(
            self.tutk_platform_lib, self.max_num_av_channels or c_int(1)
        )
        print(f"[DEBUG-IOTC] av_initialize returned: {actual_num_chans}", flush=True)
        if int(actual_num_chans) < 0:
            print(f"[DEBUG-IOTC] av_initialize FAILED: {actual_num_chans}", flush=True)
            raise tutk.TutkError(actual_num_chans)

        self.max_num_av_channels = actual_num_chans
        atexit.register(self.deinitialize)
        print(
            f"[DEBUG-IOTC] TUTK initialized OK, max channels: {actual_num_chans}",
            flush=True,
        )

    def deinitialize(self):
        """Deinitialize the underlying TUTK library.

        This is called automatically by the context manager
        """
        if self.initd:
            tutk.av_deinitialize(self.tutk_platform_lib)
            tutk.iotc_deinitialize(self.tutk_platform_lib)
            self.initd = False

    @property
    def version(self):
        """Get the version of the underlying TUTK library."""
        return tutk.iotc_get_version(self.tutk_platform_lib)

    def __enter__(self):
        self.initialize()
        return self

    def __exit__(self, exc_type, exc_value, exc_traceback):
        self.deinitialize()

    def session(self, stream, state) -> "WyzeIOTCSession":
        logger.info(f"[DEBUG] Creating session for {stream.camera.nickname}")
        return WyzeIOTCSession(
            self.tutk_platform_lib,
            stream.user,
            stream.camera,
            frame_size=stream.options.frame_size,
            bitrate=stream.options.bitrate,
            enable_audio=stream.options.audio,
            connect_timeout=CONNECT_TIMEOUT,
            stream_state=state,
            substream=stream.options.substream,
        )

    def connect_and_auth(
        self, account: WyzeAccount, camera: WyzeCamera
    ) -> "WyzeIOTCSession":
        """Initialize a new iotc session with the specified camera, and account information.

        The result of this method should be used as a context manager, i.e. using the 'with'
        keyword.  This allows us to automatically clean up after we're done with the session:

        ```python
        with WyzeIOTC() as iotc:
            with iotc.connect_and_auth(account, camera) as session:
                ...  # send configuration commands, or stream video from the session.
        ```

        See [WyzeIOTCSession](../iotc_session/) for more info.

        :param account: the account object returned from [wyzecam.api.get_user_info][]
        :param camera: the camera object returned from [wyzecam.api.get_camera_list][]
        :returns: An object representing the Wyze IOTC Session, a [WyzeIOTCSession](../iotc_session/)
        """
        return WyzeIOTCSession(self.tutk_platform_lib, account, camera)


class WyzeIOTCSessionState(enum.IntEnum):
    """An enum describing the possible states of a WyzeIOTCSession."""

    DISCONNECTED = 0
    """Not yet connected"""

    IOTC_CONNECTING = 1
    """Currently attempting to connect the IOTC session"""

    AV_CONNECTING = 2
    """Currently attempting to connect the AV session"""

    CONNECTED = 3
    """Fully connected to the camera, but have not yet attempted to authenticate"""

    CONNECTING_FAILED = 4
    """Connection failed, no longer connected"""

    AUTHENTICATING = 5
    """Attempting to authenticate"""

    AUTHENTICATION_SUCCEEDED = 6
    """Fully connected and authenticated"""

    AUTHENTICATION_FAILED = 7
    """Authentication failed, no longer connected"""


FRAME_SIZE = {0: "HD", 1: "SD", 3: "2K", 4: "SD", 5: "2K"}


class WyzeIOTCSession:
    """An IOTC session object, used for communicating with Wyze cameras.

    This is constructed from a WyzeIOTC object:

    ```python
    with WyzeIOTC() as wyze:
        with wyze.connect_and_auth(account, camera) as session:
            ...  # send configuration commands, or stream video
    ```

    However, you can construct it manually, which can be helpful if you intend to set a
    different frame size or bitrate than the defaults:

    ```python
    with WyzeIOTCSession(lib, account, camera, bitrate=tutk.BITRATE_SD)
        ...
    ```

    > **Note:** WyzeIOTCSession is intended to be used as a context manager.  Otherwise,
    >    you will need to manually tell the session to connect and authenticate, by calling
    >    session._connect() followed by session._auth(), and session._disconnect() when you're
    >    ready to disconnect the session.

    :var tutk_platform_lib: The underlying c library (from [tutk.load_library][wyzecam.tutk.tutk.load_library])
    :var account: A [WyzeAccount][wyzecam.api_models.WyzeAccount] instance, see
                    [api.get_user_info][wyzecam.api.get_user_info]
    :var camera: A [WyzeCamera][wyzecam.api_models.WyzeCamera] instance, see
                   [api.get_camera_list][wyzecam.api.get_camera_list]
    :var preferred_frame_size: The preferred size of the video stream returned by the camera.
                                 See [wyzecam.tutk.tutk.FRAME_SIZE_1080P][].
    :var preferred_bitrate: The preferred bitrate of the video stream returned by the camera.
                              See [wyzecam.tutk.tutk.BITRATE_HD][].
    :var session_id: The id of this session, once connected.
    :var av_chan_id: The AV channel of this session, once connected.
    :var state: The current connection state of this session.  See
                [WyzeIOTCSessionState](../iotc_session_state/).
    """

    def __init__(
        self,
        tutk_platform_lib: CDLL,
        account: WyzeAccount,
        camera: WyzeCamera,
        frame_size: int = tutk.FRAME_SIZE_1080P,
        bitrate: int = tutk.BITRATE_HD,
        enable_audio: bool = True,
        connect_timeout: int = 60,
        stream_state: c_int = c_int(0),
        substream: bool = False,
    ) -> None:
        """Construct a wyze iotc session.

        :param tutk_platform_lib: The underlying c library (from
                        [tutk.load_library][wyzecam.tutk.tutk.load_library])
        :param account: A [WyzeAccount][wyzecam.api_models.WyzeAccount] instance, see
                        [api.get_user_info][wyzecam.api.get_user_info]
        :param camera: A [WyzeCamera][wyzecam.api_models.WyzeCamera] instance, see
                       [api.get_camera_list][wyzecam.api.get_camera_list]
        :param frame_size: Configures the size of the video stream returned by the camera.
                           See [wyzecam.tutk.tutk.FRAME_SIZE_1080P][].
        :param bitrate: Configures the bitrate of the video stream returned by the camera.
                        See [wyzecam.tutk.tutk.BITRATE_HD][].
        """
        self.tutk_platform_lib: CDLL = tutk_platform_lib
        self.account: WyzeAccount = account
        self.camera: WyzeCamera = camera
        self.session_id: Optional[c_int] = None
        self.av_chan_id: Optional[c_int] = None
        self.state: WyzeIOTCSessionState = WyzeIOTCSessionState.DISCONNECTED

        self.preferred_frame_rate: int = 15
        self.preferred_frame_size: int = frame_size
        self.preferred_bitrate: int = bitrate
        self.connect_timeout: int = connect_timeout
        self.enable_audio: bool = enable_audio
        self.stream_state: c_int = stream_state
        self.audio_pipe_ready: bool = False
        self.frame_ts: float = 0.0
        self.substream: bool = substream
        self._sleep_buffer: float = 0.0
        self._connect_watchdog_fired: bool = False

    @property
    def resolution(self) -> str:
        return FRAME_SIZE.get(self.preferred_frame_size, str(self.preferred_frame_size))

    @property
    def sleep_interval(self) -> float:
        if LLHLS:  # May cause CPU to spike
            return 0

        if not self.frame_ts:
            return 1.0 / 100

        fps = 1.0 / self.preferred_frame_rate * 0.95
        delta = max(time.time() - self.frame_ts, 0.0)
        if self._sleep_buffer:
            delta += self._sleep_buffer
            self._sleep_buffer = max(self._sleep_buffer - fps, 0)

        return max(fps - delta, fps / 4)

    @property
    def pipe_name(self) -> str:
        return self.camera.name_uri + ("-sub" if self.substream else "")

    def session_check(self) -> tutk.SInfoStructEx:
        """Used by a device or a client to check the IOTC session info.

        A device or a client may use this function to check if the IOTC session is
        still alive as well as getting the IOTC session info.

        :returns: A [`tutk.SInfoStruct`][wyzecam.tutk.tutk.SInfoStruct]
        """
        assert self.session_id is not None, (
            "Please call _connect() before session_check()"
        )

        errcode, sess_info = tutk.iotc_session_check(
            self.tutk_platform_lib, self.session_id
        )
        if errcode < 0:
            raise tutk.TutkError(errcode)

        return sess_info

    def iotctrl_mux(self, block: bool = True) -> TutkIOCtrlMux:
        """Construct a new TutkIOCtrlMux for this session.

        Use this to send configuration messages, such as change the cameras resolution.

        Note that you either should treat the result of this as a context manager (using
        with), or call start_listening() explicitly on the result.  This starts a separate
        thread listening for the responses from the camera.

        ```python
        with session.ioctrl_mux() as mux:
            msg = tutk_protocol.K10056SetResolvingBit(
                tutk.FRAME_SIZE_1080P, tutk.BITRATE_SD)
            future = mux.send_ioctl(msg)
            assert future.result() == True, "Change bitrate failed!"
        ```

        """
        assert self.av_chan_id is not None, (
            "Please call _connect() before iotctrl_mux()!"
        )
        return TutkIOCtrlMux(self.tutk_platform_lib, self.av_chan_id, block)

    def __enter__(self):
        self._connect()
        self._auth()
        return self

    def __exit__(self, exc_type, exc_value, exc_traceback):
        self._disconnect()

    def check_native_rtsp(self, start_rtsp: bool = False) -> Optional[str]:
        """Check if Firmware supports RTSP.

        Return a local rtsp url if native stream is available.

        :param start_rtsp: Bool to start the RTSP if available but disabled in the app.

        :returns: A string with the rtsp url or None.
        """

        if not self.camera.rtsp_fw:
            return

        with self.iotctrl_mux() as mux:
            try:
                resp = mux.send_ioctl(tutk_protocol.K10604GetRtspParam()).result(
                    timeout=5
                )
            except Exception:
                logger.warning("[IOTC] RTSP Check Failed.")
                return
        if not resp:
            logger.info("[IOTC] Could not determine if RTSP is supported.")
            return
        logger.debug(f"[IOTC] {resp=}")
        if not resp[0]:
            logger.info("[IOTC] RTSP disabled in the app.")
            if not start_rtsp:
                return
            try:
                with self.iotctrl_mux() as mux:
                    mux.send_ioctl(tutk_protocol.K10600SetRtspSwitch()).result(
                        timeout=5
                    )
            except Exception:
                logger.warning("[IOTC] Can't start RTSP server on camera.")
                return
        if len(decoded_url := resp.decode().split("rtsp://")) > 1:
            return f"rtsp://{decoded_url[1]}"

    def recv_bridge_data(
        self,
    ) -> Iterator[Tuple[bytes, Union[tutk.FrameInfoStruct, tutk.FrameInfo3Struct]]]:
        """A generator for returning raw video frames for the bridge.

        Note that the format of this data is either raw h264 or HVEC H265 video. You will
        have to introspect the frame_info object to determine the format!
        """
        assert self.av_chan_id is not None, "Please call _connect() first!"
        self.sync_camera_time()

        have_key_frame = False
        while self.should_stream(sleep=self.sleep_interval):
            if not self._received_first_frame(have_key_frame):
                have_key_frame = True
                continue

            err_no, frame_data, frame_info, _ = tutk.av_recv_frame_data(
                self.tutk_platform_lib, self.av_chan_id
            )

            if not frame_data or err_no < 0:
                self._handle_frame_error(err_no)
                continue

            assert frame_info is not None, "Empty frame_info without an error!"

            if self._invalid_frame_size(frame_info, have_key_frame):
                have_key_frame = False
                continue

            if have_key_frame:
                self._video_frame_slow(frame_info)

            if frame_info.is_keyframe:
                have_key_frame = True

            yield frame_data, frame_info

        self.state = WyzeIOTCSessionState.CONNECTING_FAILED
        return b"", None

    def _received_first_frame(self, have_key_frame: bool) -> bool:
        """Check if the first frame is received and update frame size."""
        if (delta := time.time() - self.frame_ts) < self.connect_timeout:
            return True

        if have_key_frame:
            self.state = WyzeIOTCSessionState.CONNECTING_FAILED
            raise RuntimeError(f"Did not receive a frame for {int(delta)}s")

        warnings.warn("[IOTC] Still waiting for first frame. Updating frame size.")
        self.update_frame_size_rate()
        return False

    def _invalid_frame_size(self, frame_info, have_key_frame) -> bool:
        if frame_info.frame_size in self.valid_frame_size():
            return False

        self.flush_pipe("audio")
        if not have_key_frame:
            warnings.warn(
                f"[IOTC] Skipping wrong frame_size at start of stream [{frame_info.frame_size=}]"
            )
            return True

        warnings.warn(f"[IOTC] Wrong ({frame_info.frame_size=})")
        self.update_frame_size_rate()
        return True

    def _video_frame_slow(self, frame_info) -> Optional[bool]:
        # Some cams can't sync and don't sync on no audio
        if frame_info.timestamp < 1591069888:
            self.frame_ts = time.time()
            return

        self.frame_ts = float(f"{frame_info.timestamp}.{frame_info.timestamp_ms}")
        gap = time.time() - self.frame_ts

        if gap > 5:
            logger.info(f"[IOTC]] video super slow {gap=}")
            self.clear_buffer()
        if gap > 1:
            logger.debug(f"[IOTC] video slow {gap=}")
            self.flush_pipe("audio", gap)
        if gap > 0:
            self._sleep_buffer += gap

    def _handle_frame_error(self, err_no: int) -> None:
        """Handle errors that occur when receiving frame data."""
        if err_no >= 0:
            return

        if err_no == tutk.AV_ER_DATA_NOREADY:
            time.sleep(1.0 / 80)
            return

        logger.warning(f"[IOTC] {tutk.TutkError(err_no).name}")

        if err_no not in {tutk.AV_ER_INCOMPLETE_FRAME, tutk.AV_ER_LOSED_THIS_FRAME}:
            raise tutk.TutkError(err_no)

    def should_stream(self, sleep: float = 0.01) -> bool:
        time.sleep(sleep)
        return (
            self.state == WyzeIOTCSessionState.AUTHENTICATION_SUCCEEDED
            and self.stream_state.value > 1
        )

    def valid_frame_size(self) -> set[int]:
        """
        Valid frame_size for camera.

        Doorbell returns frame_size 3 or 4;
        2K returns frame_size=4
        """
        alt = self.preferred_frame_size + (1 if self.preferred_frame_size >= 3 else 3)

        return {self.preferred_frame_size, int(os.getenv("IGNORE_RES", alt))}

    def sync_camera_time(self, wait: bool = False):
        with contextlib.suppress(tutk_ioctl_mux.Empty, tutk.TutkError):
            with self.iotctrl_mux(False) as mux:
                mux.send_ioctl(tutk_protocol.K10092SetCameraTime()).result(wait)
        self.frame_ts = time.time()

    def set_resolving_bit(self, fps: int = 0):
        if fps or self.camera.product_model in {
            "WYZEDB3",
            "WVOD1",
            "HL_WCO2",
            "WYZEC1",
        }:
            return K10052DBSetResolvingBit(
                self.preferred_frame_size, self.preferred_bitrate, fps
            )

        return K10056SetResolvingBit(self.preferred_frame_size, self.preferred_bitrate)

    def update_frame_size_rate(self, bitrate: Optional[int] = None, fps: int = 0):
        """Send a message to the camera to update the frame_size and bitrate."""
        if bitrate:
            self.preferred_bitrate = bitrate

        if fps and fps != self.preferred_frame_rate:
            self.preferred_frame_rate = fps
            self.sync_camera_time()

        params = self.preferred_frame_size, self.preferred_bitrate, fps
        logger.warning("[IOTC] Requesting frame_size=%d, bitrate=%d, fps=%d" % params)

        with self.iotctrl_mux() as mux:
            with contextlib.suppress(tutk_ioctl_mux.Empty):
                mux.send_ioctl(self.set_resolving_bit(fps)).result(False)

    def clear_buffer(self) -> None:
        """Clear local buffer."""
        warnings.warn("[IOTC] clear buffer")
        assert self.av_chan_id is not None, (
            "Please call _connect() before calling clear_buffer()!"
        )
        self.sync_camera_time(True)
        tutk.av_client_clean_local_buf(self.tutk_platform_lib, self.av_chan_id)

    def flush_pipe(self, pipe_type: str = "audio", gap: float = 0):
        if pipe_type == "audio" and not self.audio_pipe_ready:
            return

        fifo = f"/tmp/{self.pipe_name}_{pipe_type}.pipe"
        size = (round(abs(gap)) * 320) if gap else 7680

        try:
            fd = os.open(fifo, os.O_RDWR)
            os.set_blocking(fd, False)
            with os.fdopen(fd, "rb", buffering=0) as pipe:
                while data_read := pipe.read(size):
                    logger.debug(
                        f"[IOTC] Flushed {len(data_read)} from {pipe_type} pipe"
                    )
                    if gap:
                        break
        except Exception as ex:
            logger.warning(f"[IOTC] Flushing Error: [{type(ex).__name__}] {ex}")

    def recv_audio_data(self) -> Iterator[bytes]:
        assert self.av_chan_id is not None, (
            "Please call _connect() before calling recv_audio_data()!"
        )
        try:
            while self.should_stream():
                err_no, frame_data, frame_info = tutk.av_recv_audio_data(
                    self.tutk_platform_lib, self.av_chan_id
                )

                if not frame_data or err_no < 0:
                    self._handle_frame_error(err_no)
                    continue

                assert frame_info is not None, "Empty frame_info without an error!"
                self._sync_audio_frame(frame_info)

                yield frame_data

        except tutk.TutkError as ex:
            logger.warning(f"[IOTC] Error: [{type(ex).__name__}] {ex}")
        finally:
            self.state = WyzeIOTCSessionState.CONNECTING_FAILED
            logger.debug("[IOTC] Audio stream ended")

    def recv_audio_pipe(self) -> None:
        """Write raw audio frames to a named pipe."""
        fifo_path = f"/tmp/{self.pipe_name}_audio.pipe"

        with contextlib.suppress(FileExistsError):
            os.mkfifo(fifo_path)  # type: ignore (this is defined in Linux)
        try:
            with open(fifo_path, "wb", buffering=0) as audio_pipe:
                os.set_blocking(audio_pipe.fileno(), False)
                self.audio_pipe_ready = True
                for frame_data in self.recv_audio_data():
                    with contextlib.suppress(BlockingIOError):
                        audio_pipe.write(frame_data)

        except IOError as ex:
            if ex.errno != errno.EPIPE:  # Broken pipe
                logger.warning(f"[IOTC] Error: [{type(ex).__name__}] {ex}")
        finally:
            self.audio_pipe_ready = False
            with contextlib.suppress(FileNotFoundError):
                os.unlink(fifo_path)
            logger.debug("[IOTC] Audio pipe closed")

    def _sync_audio_frame(self, frame_info):
        # Some cams can't sync
        if frame_info.timestamp < 1591069888:
            return

        gap = float(f"{frame_info.timestamp}.{frame_info.timestamp_ms}") - self.frame_ts

        if abs(gap) > 5:
            logger.debug(f"[IOTC] Audio out of sync {gap=}")
            self.clear_buffer()

        if gap < -1:
            logger.debug(f"[IOTC] Audio behind video.. {gap=}")
            self.flush_pipe("audio", gap)

        if gap > 0:
            self._sleep_buffer += gap
        if gap > 1:
            logger.debug(f"[ITOC] Audio ahead of video.. {gap=}")
            time.sleep(gap / 2)

    def get_audio_sample_rate(self) -> int:
        """Attempt to get the audio sample rate."""
        if self.camera.camera_info and "audioParm" in self.camera.camera_info:
            audio_param = self.camera.camera_info["audioParm"]
            return int(audio_param.get("sampleRate", self.camera.default_sample_rate))

        return self.camera.default_sample_rate

    def get_audio_codec_from_codec_id(self, codec_id: int) -> tuple[str, int]:
        sample_rate = self.get_audio_sample_rate()

        codec_mapping = {
            137: ("mulaw", sample_rate),
            140: ("s16le", sample_rate),
            141: ("aac", sample_rate),
            143: ("alaw", sample_rate),
            144: ("aac", 16000),  # aac_eld
            146: ("opus", 16000),
        }

        codec, sample_rate = codec_mapping.get(codec_id, (None, None))

        if not codec:
            raise RuntimeError(f"\nUnknown audio codec {codec_id=}\n")

        logger.info(f"[IOTC] Audio {codec=} {sample_rate=} {codec_id=}")
        return codec, sample_rate or 16000

    def identify_audio_codec(self, limit: int = 60) -> tuple[str, int]:
        """Identify audio codec."""
        assert self.av_chan_id is not None, "Please call _connect() first!"

        for _ in range(limit):
            err_no, _, frame_info = tutk.av_recv_audio_data(
                self.tutk_platform_lib, self.av_chan_id
            )
            if not err_no and frame_info and frame_info.codec_id:
                return self.get_audio_codec_from_codec_id(frame_info.codec_id)
            time.sleep(0.05)

        raise RuntimeError("Unable to identify audio.")

    def _connect_watchdog_timeout(self) -> Optional[float]:
        if self.camera.product_model != "HL_CAM4":
            return None

        if not (self.substream or _hl_cam4_main_probe_mode() in {"tutk_dtls", "tutk_parallel"}):
            return None

        return _hl_cam4_connect_watchdog_secs()

    def _arm_connect_watchdog(
        self, connect_mode: str
    ) -> tuple[Optional[threading.Timer], threading.Event]:
        connect_done = threading.Event()
        self._connect_watchdog_fired = False
        timeout_s = self._connect_watchdog_timeout()
        if timeout_s is None or self.session_id is None:
            return None, connect_done

        _log_tutk_trace(
            self.camera,
            "connect_watchdog_armed",
            connect_mode=connect_mode,
            substream=self.substream,
            watchdog_timeout_s=round(timeout_s, 3),
        )

        def stop_connect() -> None:
            if connect_done.is_set() or self.session_id is None:
                return

            print(
                f"[DEBUG-IOTC] Connect watchdog firing after {timeout_s:.3f}s for {self.camera.nickname}",
                flush=True,
            )
            self._connect_watchdog_fired = True
            _log_tutk_trace(
                self.camera,
                "connect_watchdog_timeout",
                connect_mode=connect_mode,
                substream=self.substream,
                watchdog_timeout_s=round(timeout_s, 3),
            )
            err_no = tutk.iotc_connect_stop_by_session_id(
                self.tutk_platform_lib, self.session_id
            )
            _log_tutk_trace(
                self.camera,
                "connect_watchdog_stop",
                connect_mode=connect_mode,
                errno=int(err_no),
                substream=self.substream,
            )
            print(
                f"[DEBUG-IOTC] Connect watchdog stop returned {int(err_no)} for {self.camera.nickname}",
                flush=True,
            )

        watchdog = threading.Timer(timeout_s, stop_connect)
        watchdog.daemon = True
        watchdog.start()
        return watchdog, connect_done

    def _release_connect_watchdog(
        self,
        watchdog: Optional[threading.Timer],
        connect_done: threading.Event,
    ) -> None:
        connect_done.set()
        if not watchdog:
            return

        watchdog.cancel()
        with contextlib.suppress(RuntimeError):
            watchdog.join(timeout=0.1)

    def _run_connect_with_watchdog(
        self, connect_mode: str, connect_call: Callable[[], int]
    ) -> int:
        watchdog, connect_done = self._arm_connect_watchdog(connect_mode)
        try:
            return connect_call()
        finally:
            self._release_connect_watchdog(watchdog, connect_done)

    def _retryable_connect_error(self, ex: tutk.TutkError) -> bool:
        if ex.code in {-13, -23}:
            return True
        return ex.code == -27 and self._connect_watchdog_fired

    def _connect(
        self,
        timeout_secs: c_uint32 = c_uint32(20),
        channel_id: c_ubyte = c_ubyte(0),
        username: str = "admin",
        password: str = "888888",
        max_buf_size: c_uint = c_uint(10 * 1024 * 1024),
    ):
        max_retries = max(int(os.getenv("CONNECT_RETRIES", 3)), 1)
        retry_delay = max(float(os.getenv("CONNECT_RETRY_DELAY", 2.0)), 0.0)
        last_error = None

        for attempt in range(max_retries):
            try:
                self._connect_attempt(
                    timeout_secs,
                    channel_id,
                    username,
                    password,
                    max_buf_size,
                    attempt_no=attempt + 1,
                    max_retries=max_retries,
                )
                return
            except tutk.TutkError as ex:
                last_error = ex
                if not self._retryable_connect_error(ex) or attempt == max_retries - 1:
                    raise

                logger.warning(
                    f"[IOTC] Connection failed for {self.camera.nickname} with {ex.code}; retrying {attempt + 2}/{max_retries} in {retry_delay:.1f}s"
                )
                self._disconnect()
                time.sleep(retry_delay)

        if last_error:
            raise last_error

    def _connect_attempt(
        self,
        timeout_secs: c_uint32 = c_uint32(20),
        channel_id: c_ubyte = c_ubyte(0),
        username: str = "admin",
        password: str = "888888",
        max_buf_size: c_uint = c_uint(10 * 1024 * 1024),
        attempt_no: int = 1,
        max_retries: int = 1,
    ):
        try:
            self.state = WyzeIOTCSessionState.IOTC_CONNECTING
            print(
                f"[DEBUG-IOTC] _connect() starting for {self.camera.nickname} ({self.camera.product_model})",
                flush=True,
            )
            print(
                f"[DEBUG-IOTC] P2P ID present: {bool(self.camera.p2p_id)}", flush=True
            )
            assert self.camera.p2p_id, "Missing p2p_id"

            print("[DEBUG-IOTC] Getting session ID...", flush=True)
            session_id = tutk.iotc_get_session_id(self.tutk_platform_lib)
            if int(session_id) < 0:
                print(f"[DEBUG-IOTC] get_session_id FAILED: {session_id}", flush=True)
                raise tutk.TutkError(session_id)
            self.session_id = session_id
            print(f"[DEBUG-IOTC] Got session ID: {session_id}", flush=True)

            force_v4_parallel_raw = os.getenv("FORCE_V4_PARALLEL", "")
            probe_mode = _hl_cam4_main_probe_mode()
            force_parallel_substream = self.substream and self.camera.product_model in {
                "HL_CAM3P",
                "HL_CAM4",
            }
            force_v4_parallel = (
                self.camera.product_model == "HL_CAM4"
                and (
                    probe_mode == "tutk_parallel"
                    or force_v4_parallel_raw.lower() in {"1", "true", "yes"}
                )
            )
            print(
                f"[DEBUG-IOTC] FORCE_V4_PARALLEL raw='{force_v4_parallel_raw}' active={force_v4_parallel or force_parallel_substream}",
                flush=True,
            )
            _log_tutk_trace(
                self.camera,
                "connect_start",
                attempt_no=attempt_no,
                av_chan_id=None,
                dtls=self.camera.dtls,
                force_v4_parallel=force_v4_parallel or force_parallel_substream,
                max_retries=max_retries,
                main_probe_mode=probe_mode,
                parent_dtls=self.camera.parent_dtls,
                session_id=int(self.session_id),
                substream=self.substream,
            )

            if force_parallel_substream or force_v4_parallel or (
                not self.camera.dtls and not self.camera.parent_dtls
            ):
                connect_mode = "parallel"
                print(
                    "[DEBUG-IOTC] Using IOTC_Connect_ByUID_Parallel"
                    + (
                        " (forced substream)"
                        if force_parallel_substream
                        else " (forced HL_CAM4)"
                        if force_v4_parallel
                        else " (no DTLS)"
                    ),
                    flush=True,
                )
                connect_started = time.monotonic()
                session_id = self._run_connect_with_watchdog(
                    connect_mode,
                    lambda: tutk.iotc_connect_by_uid_parallel(
                        self.tutk_platform_lib, self.camera.p2p_id, self.session_id
                    ),
                )
                print(
                    f"[DEBUG-IOTC] iotc_connect_by_uid_parallel elapsed={time.monotonic() - connect_started:.3f}s",
                    flush=True,
                )
            else:
                connect_mode = "dtls_ex"
                print(
                    f"[DEBUG-IOTC] Using IOTC_Connect_ByUIDEx (DTLS={self.camera.dtls})",
                    flush=True,
                )
                password = (
                    str(self.camera.parent_enr)
                    if self.camera.parent_dtls
                    else str(self.camera.enr)
                )
                print("[DEBUG-IOTC] Calling iotc_connect_by_uid_ex...", flush=True)
                connect_started = time.monotonic()
                session_id = self._run_connect_with_watchdog(
                    connect_mode,
                    lambda: tutk.iotc_connect_by_uid_ex(
                        self.tutk_platform_lib,
                        self.camera.p2p_id,
                        self.session_id,
                        self.get_auth_key(),
                        self.connect_timeout,
                    ),
                )
                print(
                    f"[DEBUG-IOTC] iotc_connect_by_uid_ex elapsed={time.monotonic() - connect_started:.3f}s",
                    flush=True,
                )
            connect_elapsed = round(time.monotonic() - connect_started, 3)
            _log_tutk_trace(
                self.camera,
                "connect_result",
                attempt_no=attempt_no,
                connect_mode=connect_mode,
                elapsed_s=connect_elapsed,
                max_retries=max_retries,
                session_id=int(session_id),
                substream=self.substream,
                watchdog_fired=self._connect_watchdog_fired,
            )

            print(f"[DEBUG-IOTC] Connect returned: {session_id}", flush=True)
            if int(session_id) < 0:
                print(
                    f"[DEBUG-IOTC] Session connection FAILED: {int(session_id)}",
                    flush=True,
                )
                raise tutk.TutkError(session_id)
            self.session_id = session_id
            print(f"[DEBUG-IOTC] Session connected OK: {session_id}", flush=True)

            print("[DEBUG-IOTC] Calling session_check...", flush=True)
            session_info = self.session_check()
            print(
                f"[DEBUG-IOTC] Session mode: {session_info.mode} (0=P2P, 1=Relay, 2=LAN)",
                flush=True,
            )
            _log_tutk_trace(
                self.camera,
                "session_check",
                session_mode=int(session_info.mode),
                substream=self.substream,
            )
            resend = (
                c_int(1)
                if self.camera.product_model not in ("WVOD1", "HL_WCO2")
                and int(os.getenv("RESEND", 1)) != 0
                else c_int(0)
            )

            self.state = WyzeIOTCSessionState.AV_CONNECTING
            logger.debug(
                f"[IOTC] Calling av_client_start {session_id=} {username=} password: {redact_password(password)} {timeout_secs=} {channel_id=} {resend=}"
            )
            av_chan_id = tutk.av_client_start(
                self.tutk_platform_lib,
                self.session_id,
                username.encode("ascii"),
                password.encode("ascii"),
                timeout_secs,
                channel_id,
                resend,
            )
            logger.debug(f"[IOTC] av_client_start returned {av_chan_id=}")
            _log_tutk_trace(
                self.camera,
                "av_client_start",
                av_chan_id=int(av_chan_id),
                substream=self.substream,
            )

            if int(av_chan_id) < 0:
                logger.error(
                    f"[DEBUG] AV client start failed with error code: {int(av_chan_id)}"
                )
                raise tutk.TutkError(av_chan_id)
            self.av_chan_id = av_chan_id
            self.state = WyzeIOTCSessionState.CONNECTED
            logger.info(f"[DEBUG] AV Client connected successfully: {av_chan_id}")
        except tutk.TutkError as e:
            _log_tutk_trace(
                self.camera,
                "connect_error",
                code=e.code,
                error=str(e),
                substream=self.substream,
            )
            logger.error(f"[DEBUG] TutkError in _connect: code={e.code}, message={e}")
            self._disconnect()
            raise
        finally:
            if self.state != WyzeIOTCSessionState.CONNECTED:
                self.state = WyzeIOTCSessionState.CONNECTING_FAILED

        logger.info(
            f"[IOTC] AV Client Start: {self.av_chan_id=} expected_chan={channel_id}"
        )

        self.tutk_platform_lib.avClientSetMaxBufSize(max_buf_size)
        tutk.av_client_set_recv_buf_size(
            self.tutk_platform_lib, self.av_chan_id or c_int(0), max_buf_size
        )

    def get_auth_key(self) -> str:
        """Generate authkey using enr and mac address."""
        auth = (
            str(self.camera.parent_enr) + str(self.camera.parent_mac).upper()
            if self.camera.parent_dtls
            else str(self.camera.enr) + self.camera.mac.upper()
        )
        hashed_enr = hashlib.sha256(auth.encode("utf-8")).digest()
        auth_key = (
            base64.b64encode(hashed_enr[:6])
            .decode()
            .replace("+", "Z")
            .replace("/", "9")
            .replace("=", "A")
            # .encode() # https://github.com/kroo/wyzecam/compare/main...mrlt8:wyzecam:dev#diff-ed2b3d2defa5e765636d4536ebf34452e05bfec37377d62c71a9e58789e093dfR667
        )
        return auth_key

    def _auth(self):
        if self.state == WyzeIOTCSessionState.CONNECTING_FAILED:
            logger.error("[DEBUG] _auth() called but state is CONNECTING_FAILED")
            return

        assert self.state == WyzeIOTCSessionState.CONNECTED, (
            f"Auth expected state to be connected but not authed; state={self.state.name}"
        )

        self.state = WyzeIOTCSessionState.AUTHENTICATING
        logger.info(f"[DEBUG] _auth() starting for {self.camera.nickname}")
        _log_tutk_trace(self.camera, "auth_start", substream=self.substream)
        try:
            with self.iotctrl_mux() as mux:
                wake_mac = None
                if self.camera.product_model in {"WVOD1", "HL_WCO2"}:
                    wake_mac = self.camera.mac
                    logger.info(
                        f"[DEBUG] Using wake_mac for outdoor camera: {wake_mac}"
                    )

                logger.info("[DEBUG] Sending K10000ConnectRequest...")
                challenge = mux.send_ioctl(K10000ConnectRequest(wake_mac))
                result = challenge.result()

                if not result:
                    logger.error(f"[DEBUG] K10000ConnectRequest failed: {challenge}")
                    warnings.warn(f"[IOTC] CONNECT FAILED: {challenge}")
                    raise ValueError("CONNECT_REQUEST_FAILED")

                logger.info(f"[IOTC] {challenge.resp_protocol=}")
                logger.info(
                    f"[DEBUG] Challenge result received, protocol: {challenge.resp_protocol}"
                )
                _log_tutk_trace(
                    self.camera,
                    "auth_challenge",
                    resp_protocol=challenge.resp_protocol,
                    substream=self.substream,
                )

                challenge_response = respond_to_ioctrl_10001(
                    result,
                    challenge.resp_protocol or 0,
                    str(self.camera.enr) + str(self.camera.parent_enr),
                    self.camera.product_model,
                    self.camera.mac,
                    self.account.phone_id,
                    self.account.open_user_id,
                    self.enable_audio,
                )

                if not challenge_response:
                    logger.error("[DEBUG] challenge_response is None - AUTH_FAILED")
                    raise ValueError("AUTH_FAILED")

                logger.info("[DEBUG] Sending challenge response...")
                auth_response = mux.send_ioctl(challenge_response).result()

                if not auth_response:
                    logger.error("[DEBUG] auth_response is None - AUTH_RESPONSE_NONE")
                    raise ValueError("AUTH_RESPONSE_NONE")

                logger.info(
                    f"[DEBUG] Auth response received: connectionRes={auth_response.get('connectionRes')}"
                )
                _log_tutk_trace(
                    self.camera,
                    "auth_response",
                    connection_res=auth_response.get("connectionRes"),
                    substream=self.substream,
                )

                if auth_response["connectionRes"] == "2":
                    logger.error("[DEBUG] connectionRes=2 - ENR_AUTH_FAILED")
                    raise ValueError("ENR_AUTH_FAILED")

                if auth_response["connectionRes"] != "1":
                    logger.error(
                        f"[DEBUG] connectionRes={auth_response.get('connectionRes')} - AUTH_FAILED"
                    )
                    warnings.warn(f"[IOTC] AUTH FAILED: {auth_response=}")
                    raise ValueError("AUTH_FAILED")

                logger.info("[DEBUG] Authentication successful, setting camera info...")
                self.camera.set_camera_info(auth_response["cameraInfo"])

                mux.send_ioctl(self.set_resolving_bit()).result()
                self.state = WyzeIOTCSessionState.AUTHENTICATION_SUCCEEDED
                _log_tutk_trace(
                    self.camera,
                    "auth_success",
                    bitrate=self.preferred_bitrate,
                    frame_size=self.preferred_frame_size,
                    substream=self.substream,
                )
                logger.info("[DEBUG] Authentication completed successfully")
        except tutk.TutkError as e:
            _log_tutk_trace(
                self.camera,
                "auth_error",
                code=e.code,
                error=str(e),
                substream=self.substream,
            )
            logger.error(f"[DEBUG] TutkError in _auth: code={e.code}, message={e}")
            self._disconnect()
            raise
        except ValueError as e:
            _log_tutk_trace(
                self.camera,
                "auth_error",
                error=str(e),
                substream=self.substream,
            )
            logger.error(f"[DEBUG] ValueError in _auth: {e}")
            raise
        finally:
            if self.state != WyzeIOTCSessionState.AUTHENTICATION_SUCCEEDED:
                self.state = WyzeIOTCSessionState.AUTHENTICATION_FAILED
                logger.error(
                    f"[DEBUG] Authentication failed, state set to: {self.state.name}"
                )
        return self

    def _disconnect(self):
        if self.av_chan_id is not None:
            tutk.av_send_io_ctrl_exit(self.tutk_platform_lib, self.av_chan_id)
            tutk.av_client_stop(self.tutk_platform_lib, self.av_chan_id)

        self.av_chan_id = None

        if self.session_id is not None:
            err_no = tutk.iotc_connect_stop_by_session_id(
                self.tutk_platform_lib, self.session_id
            )
            if int(err_no) < 0:
                warning = Warning(tutk.TutkError(err_no), err_no)
                warnings.warn(warning)
            tutk.iotc_session_close(self.tutk_platform_lib, self.session_id)

        self.session_id = None
        self.state = WyzeIOTCSessionState.DISCONNECTED


def redact_password(password: Optional[str]):
    return f"{password[0]}{'*' * (len(password) - 1)}" if password else "NOT SET"

# Docker Wyze Bridge

## Authentication

The standard Home Assistant setup path uses the visible `Wyze email`, `Wyze password`, `Key ID`, and `API key` fields on the add-on configuration page.

As of April 2024, Wyze developer credentials are required. See the official guide:

`https://support.wyze.com/hc/en-us/articles/16129834216731`

## Recommended Setup Order

Fill these in first:

- `Wyze email`
- `Wyze password`
- `Key ID`
- `API key`

Common optional defaults near the top of the add-on form:

- `Connect on demand`
- `Enable audio by default`
- `Default HD quality request`
- `Default SD quality request`
- `Create SD substream by default`
- `Camera Specific Options`

The add-on form is intentionally focused on the common Home Assistant setup path. Rare power-user settings are kept out of the page so the form stays manageable.

## Stream Surfaces

### Standard bridge ports

- RTSP: `rtsp://homeassistant.local:58554/camera-name`
- HLS: `http://homeassistant.local:58888/camera-name/stream.m3u8`
- WebRTC / WHEP: `http://homeassistant.local:58889/camera-name`
- Web UI: `http://homeassistant.local:5000`

### Native Home Assistant `go2rtc` sidecar

- Supported RTSP surface: `rtsp://homeassistant.local:19554/camera-name`
- Internal sidecar API: `http://homeassistant.local:11984/api`

Important:

- `:19554` is the supported public sidecar surface in `4.2`.
- `:11984` is an internal implementation detail and not part of the stable public interface.
- A `-sd` alias may exist for some cameras, but it is only useful when the camera exposes a meaningful second stream.

## Camera-Specific Limits

The public `4.2` release intentionally documents current limits rather than implying every modern Wyze model behaves the same.

- Wyze Cam V3: bridge main and firmware-gated bridge substream are supported; validated V3-class paths have reached `1920x1080`.
- Wyze Cam V3 Pro: bridge main validated at `2560x1440`; `4.2` does not promise a fixed substream ceiling for every installation.
- Wyze Cam V4: standard bridge RTSP may remain `640x360`; validated Home Assistant native sidecar output reached `2560x1440` main and `640x360` substream.
- Wyze Bulb Cam: supported, but current public validation keeps both main and `-sd` at `640x360`.

See [Camera Support](../docs/user_guide/camera_support.md) for the detailed matrix.

## Stream and API Authentication

When `WB_AUTH` is enabled, streams and API endpoints require authentication.

- REST API example: `http://homeassistant.local:5000/api/<camera-name>/state?api=<your-wb-api-key>`
- Stream username: `wb`
- Stream password: your unique Web UI password or API key, depending on configuration

Do not forward bridge or RTSP ports to the public internet unless you understand the security implications.

## Camera-Specific Options

Camera-specific options can be passed using `CAM_OPTIONS`.

```yaml
- CAM_NAME: Front
  HD: true
  SD: true
  SD_KBPS: 60
  AUDIO: true
  ROTATE: true
- CAM_NAME: Back door
  HD: false
  SD: true
  RECORD: true
```

Available options:

- `HD` enables the higher-quality feed for that camera.
- `SD` enables the lower-bandwidth feed for that camera.
- Explicit `HD` and `SD` values in `CAM_OPTIONS` act as the default runtime feed state even before any camera settings are saved from the Web UI.
- `HD_KBPS` and `SD_KBPS` set per-feed bitrate targets.
- `AUDIO` enables audio for that camera.
- `STREAM` is the older `main` / `both` / `sub` shortcut. Prefer `HD` and `SD` for new setups.
- `QUALITY` and `SUB_QUALITY` override the requested quality for that camera.
- `FORCE_FPS` sets frames per second.
- `RECORD` and `SUB_RECORD` control recording for each feed.
- `SUBSTREAM` enables a `-sub` path only when the camera path supports it.
- `NET_MODE` overrides the allowed network mode.
- `ROTATE` rotates the camera clockwise.
- `LIVESTREAM` sends that camera to an RTMP target.
- `MOTION_WEBHOOKS` posts to a webhook when motion is detected.
- `FFMPEG` uses a custom ffmpeg command for that camera.

The Web UI also exposes a per-camera stream mode control for `Main`, `Both`, or `Sub`. Cameras without supported substreams keep the `Sub` option disabled in the UI.

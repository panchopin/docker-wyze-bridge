# Docker Wyze Bridge (Dev Build)

This add-on is the local staging build for SSH-driven validation. It is not the public production add-on.

## Before You Start

- Keep the production add-on installed and unchanged.
- Copy production settings into this dev add-on before testing.
- The dev add-on uses its own host-network port block, but stop production first when you need exact parity checks or want to avoid split-environment confusion.
- Restore production after each test cycle.

## Wyze Authentication

This staging add-on should use the same login path and settings as production. The standard Home Assistant setup path uses the visible `Wyze email`, `Wyze password`, `Key ID`, and `API key` fields on the add-on configuration page.

As of April 2024, you will need to supply your own API Key and API ID along with your Wyze email and password.

See the official help documentation on how to generate your developer keys: https://support.wyze.com/hc/en-us/articles/16129834216731.

## Recommended Setup Order

Fill these in first:

- `Wyze email`
- `Wyze password`
- `Key ID`
- `API key`

Common optional defaults near the top of the add-on form:

- `Connect on demand`
- `Enable audio by default`
- `Create SD substream by default`
- `Camera Specific Options`

The add-on form is intentionally focused on the common Home Assistant setup path. Rare power-user settings are kept out of the page so the form stays manageable.

## Stream and API Authentication

Note that all streams and the REST API will necessitate authentication when WebUI Auth `WB_AUTH` is enabled.

- REST API will require an `api` query parameter.
  - Example: `http://homeassistant.local:55000/api/<camera-name>/state?api=<your-wb-api-key>`
- Streams will also require authentication.
  - username: `wb`
  - password: your unique wb api key

Please double check your router/firewall and do NOT forward ports or enable DMZ access to your bridge/server unless you know what you are doing.


## Camera Specific Options

Camera specific options can now be passed to the bridge using `CAM_OPTIONS`. To do so you, will need to specify the `CAM_NAME` and the option(s) that you want to pass to the camera.

`CAM_OPTIONS`:

```YAML
- CAM_NAME: Front
  HD: true
  SD: true
  AUDIO: true
  ROTATE: true
- CAM_NAME: Back door
  HD: false
  SD: true
  RECORD: true
```

Available options:

- `HD` - Enable the higher-quality feed for this camera.
- `SD` - Enable the lower-bandwidth feed for this camera.
- `AUDIO` - Enable audio for this camera.
- `STREAM` - Older `main`, `both`, or `sub` shortcut. Prefer `HD` and `SD` for new setups.
- `FORCE_FPS` - Set the frames-per-second for this camera.
- `RECORD` and `SUB_RECORD` - Enable recording for each feed.
- `SUBSTREAM` - Enable a `-sub` path for this camera when the path supports it.
- `NET_MODE` - Change the allowed net mode for this camera only.
- `ROTATE` - Rotate this camera 90 degrees clockwise.
- `LIVESTREAM` - Specify an RTMP URL to livestream to for this camera.
- `MOTION_WEBHOOKS` - Specify a URL to POST to when motion is detected.
- `FFMPEG` - Use a custom FFmpeg command for this camera.

The Web UI also exposes a per-camera stream mode control for `Main`, `Both`, or `Sub`. Cameras without supported substreams keep the `Sub` option disabled in the UI.

## URIs

`camera-nickname` is the name of the camera set in the Wyze app and are converted to lower case with hyphens in place of spaces.

e.g. 'Front Door' would be `/front-door`

- RTMP:

```
rtmp://homeassistant.local:52935/camera-nickname
```

- RTSP:

```
rtsp://homeassistant.local:59554/camera-nickname
```

- WebRTC / WHEP:

```
http://homeassistant.local:59889/camera-nickname
http://homeassistant.local:59889/camera-nickname/whep
```

- HLS:

```
http://homeassistant.local:59888/camera-nickname/stream.m3u8
```

- HLS can also be viewed in the browser using:

```
http://homeassistant.local:59888/camera-nickname
```

For local staging workflow details, use the gitignored maintainer docs in this workspace under `docs/maintainer/`.

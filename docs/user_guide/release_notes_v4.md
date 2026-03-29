# Release Notes 4.2

`4.2` is a public feature release for Docker Wyze Bridge. It keeps the modern bridge path for newer Wyze cameras, carries forward the supported Home Assistant native `go2rtc` RTSP sidecar, and aligns the shared runtime and release surfaces around the newer per-camera feed controls.

## What's New

### Home Assistant native `go2rtc` sidecar

- The Home Assistant add-on now bundles `go2rtc`.
- Supported native RTSP output is exposed on `:19554`.
- The sidecar API on `:11984` remains internal and is not part of the stable public contract.

### Shared runtime and Web UI alignment

- The merged `stream-config` work is now aligned across the root app, production add-on, and dev add-on runtime trees.
- The Web UI exposes per-camera `HD` and `SD` feed publishing, separate kbps targets, feed availability state, and reported feed resolution labels.
- Shared frontend files were normalized where behavior should match, while environment-specific talkback loopback ports remain intentionally different.

### Startup and runtime hardening

- WHEP output is now gated on real upstream media readiness.
- Bridge startup no longer crashes when Wyze login succeeds but `get_user_info` is missing or empty.
- Stream iteration and bridge startup behavior are more defensive around live stream registration.

### Documentation reset

- The visible app name is now simply `Docker Wyze Bridge`.
- Public docs now include model-specific limits for `V3`, `V3 Pro`, `V4`, and `Wyze Bulb Cam`.
- Home Assistant docs now separate the supported native RTSP surface from the internal sidecar API.

## Camera Support Summary

| Model | 4.2 public summary |
| :--- | :--- |
| Wyze Cam V3 | Bridge path remains the primary documented path. Validated V3-class paths have reached `1920x1080`; firmware-gated substream support remains in place. |
| Wyze Cam V3 Pro | Bridge main validated at `2560x1440`. `4.2` does not promise a fixed substream ceiling on every installation. |
| Wyze Cam V4 | Standard bridge RTSP can still remain `640x360`. The supported Home Assistant native sidecar path is the best documented RTSP path for validated `4.2` installs, with validated native output at `2560x1440` main and `640x360` substream. |
| Wyze Bulb Cam | Supported, but current public validation keeps both main and `-sd` feeds at `640x360`. |

For the full matrix, see [Camera Support](./camera_support.md).

## Attribution

This release continues to build on work from:

- `idisposable/docker-wyze-bridge`
- `akeslo/docker-wyze-bridge`
- `kroo/wyzecam`
- `aler9/mediamtx`
- `AlexxIT/go2rtc`

The bundled Home Assistant native sidecar uses `go2rtc` from `AlexxIT/go2rtc`, licensed under MIT. See [THIRD_PARTY_NOTICES.md](../../THIRD_PARTY_NOTICES.md).

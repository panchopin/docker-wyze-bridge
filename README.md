# Docker Wyze Bridge

[![GitHub release (latest by date)](https://img.shields.io/github/v/release/thatdaveguy1/docker-wyze-bridge?logo=github)](https://github.com/thatdaveguy1/docker-wyze-bridge/releases/latest)
[![GHCR Package](https://img.shields.io/badge/ghcr-package-blue?logo=github)](https://ghcr.io/thatdaveguy1/docker-wyze-bridge)
[![Home Assistant Add-on](https://img.shields.io/badge/home_assistant-add--on-blue.svg?logo=homeassistant&logoColor=white)](./docs/user_guide/install_ha.md)

### WebRTC/RTSP/RTMP/HLS Bridge for Wyze Cameras

![Wyze Bridge UI](https://user-images.githubusercontent.com/67088095/224595527-05242f98-c4ab-4295-b9f5-07051ced1008.png)

Create local WebRTC, RTSP, RTMP, and HLS streams for Wyze cameras without custom firmware. This fork focuses on newer Wyze camera behavior, Home Assistant packaging, and the real limitations and runtime behavior validated for the 4.2 release.

- No camera firmware mods required.
- Home Assistant add-on with visible Wyze login fields by default.
- WebRTC/KVS-backed bridge path for modern Wyze models.
- Native Home Assistant `go2rtc` RTSP sidecar on `:19554` for supported 4.2 workflows.

## 4.2 Highlights

- Home Assistant and root Docker runtimes now share the same native `go2rtc` bootstrap path, with the supported RTSP sidecar surface on `:19554`.
- Camera metadata, `/health/details`, and the Web UI now expose per-camera native-vs-bridge selection plus granular `HD` and `SD` feed publishing controls.
- `frontend.py`, `site.js`, and `index.html` are normalized across the three runtime trees where behavior should match, while preserving the intentional dev add-on `:55000` talkback loopback port.
- API-first native talkback remains limited to native-selected cameras, with uploaded-audio talkback validated on native-selected V4 paths.
- Public docs and add-on/package version surfaces are aligned for the `4.2.0` release.

## Quick Start

| Platform | Guide |
| :--- | :--- |
| Home Assistant add-on | [Install Guide](./docs/user_guide/install_ha.md) |
| Docker / Compose | [Docker Install Guide](./docs/user_guide/install_docker.md) |
| Upgrade from an older fork | [Upgrade Guide](./docs/user_guide/upgrade.md) |

## Camera Support Snapshot

The `4.2` release documents the current validated ceilings rather than promising ideal output on every camera.

| Model | Default path | Main stream | Substream | Current 4.2 limit |
| :--- | :--- | :--- | :--- | :--- |
| Wyze Cam V3 | Bridge WebRTC/KVS | Validated up to `1920x1080` on V3-class paths | Supported on firmware `4.36.10+`; validated V3-class substream paths have reached `1920x1080` | `QUALITY` values do not force a higher resolution than the camera/firmware actually provides |
| Wyze Cam V3 Pro | Bridge WebRTC/KVS | Validated up to `2560x1440` | Supported on firmware `4.58.0+`; no fixed public `4.2` substream ceiling is promised | Native `go2rtc` did not show a proven public improvement on the validation host |
| Wyze Cam V4 | Bridge WebRTC/KVS, plus HA native `go2rtc` on `:19554` | Standard bridge path may remain `640x360`; validated HA native `go2rtc` main reached `2560x1440` | Standard bridge substream is not a reliable high/low split; validated HA native `go2rtc` sub reached `640x360` | TUTK fallback is not a reliable quality-rescue path in `4.2` |
| Wyze Bulb Cam | Bridge RTC/WHEP, plus HA native `go2rtc` on `:19554` | Validated compatibility, with current `4.2` main ceiling of `640x360` | No validated distinct main/sub split in `4.2`; `-sd` may mirror the same `640x360` feed | No software-only 2K path has been validated in this release |

Full caveats, firmware notes, and public limitations live in [Camera Support](./docs/user_guide/camera_support.md).

## Home Assistant Notes

- Supported native sidecar surface: `rtsp://<home-assistant-host>:19554/<camera-name>`
- Native `-sd` aliases may be available when the camera exposes a meaningful second stream.
- The sidecar API on `:11984` is an internal implementation detail and is not part of the stable public interface.
- The visible add-on name is `Docker Wyze Bridge`, while the existing Home Assistant slug stays in place for migration stability.
- The Home Assistant add-on now keeps required login fields at the top, trims the HA form down to common day-to-day settings, uses much clearer optional-setting descriptions, and supports per-camera feed selection through `CAM_OPTIONS` and the Web UI with independent `HD` and `SD` toggles, per-feed kbps targets, surfaced feed resolution labels, and disabled controls for unsupported feeds. Rare power-user knobs are kept out of the HA form so the page stays manageable. On the March 29, 2026 validation host, the live dev add-on at `:55000` now shows Bulb Cam style `HD disabled / SD enabled` state correctly and completed a browser-driven settings round-trip on a supported camera.
- The March 29, 2026 `4.2.1` bugfix follow-up also fixed an important Home Assistant defaulting gap: explicit per-camera `CAM_OPTIONS` `HD` and `SD` values now apply as the runtime defaults even when `/config/wyze_camera_settings.json` is absent, so an `SD`-only setup no longer depends on a hidden saved-settings file.

## Documentation

- [4.2 Release Notes](./docs/user_guide/release_notes_v4.md)
- [Camera Support and Limits](./docs/user_guide/camera_support.md)
- [Home Assistant Add-on Docs](./home_assistant/DOCS.md)
- [Troubleshooting Guide](./docs/user_guide/troubleshooting.md)
- [Upgrade Guide](./docs/user_guide/upgrade.md)

## Attribution

This fork builds on work from several upstream projects:

- `idisposable/docker-wyze-bridge`
- `akeslo/docker-wyze-bridge`
- `kroo/wyzecam`
- `aler9/mediamtx`
- `AlexxIT/go2rtc`

The Home Assistant native sidecar work in `4.2` bundles `go2rtc` from `AlexxIT/go2rtc`, which is licensed under MIT. See [THIRD_PARTY_NOTICES.md](./THIRD_PARTY_NOTICES.md).

> [!IMPORTANT]
> This project is not affiliated with Wyze Labs, Inc. Use at your own risk.

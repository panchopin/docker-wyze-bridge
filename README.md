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
- Public docs and add-on/package version surfaces are aligned for the `4.2.5` release.

## 4.2 Patch Releases

### 4.2.5

- Refreshes preserved native `go2rtc` Wyze aliases from the current `/api/wyze` helper output at startup instead of freezing them when a seeded config already exists.
- Installs `curl` in the runtime images so the sidecar refresh helper can actually reach the local `go2rtc` API from the running add-on.

### 4.2.4

- Fixes Home Assistant feed-selection precedence so explicit `CAM_OPTIONS` `HD` and `SD` values override stale saved per-camera feed settings.
- Stops creating a competing bridge-managed `-sub` path when the SD feed is native-selected, which prevents `north-yard-sub` churn from surviving an explicit `SD=false` setting.

### 4.2.3

- Fixes the Web UI asset path regression that could leave the app page effectively unstyled even though camera content still rendered.
- Makes the frontend bind its own `static/` and `templates/` directories explicitly in all three runtime trees and uses ingress-aware template asset URLs so CSS and JS resolve correctly under Home Assistant ingress and normal app routing.

### 4.2.2

- Hardens MQTT motion semantics for Home Assistant and Scrypted workflows.
- Fixes the BOA/LAN motion topic so MQTT publishes land on `wyzebridge/<camera>/motion` instead of the wrong double-prefixed path.
- Normalizes BOA/LAN motion payloads to the same `1` and `2` contract already used by the API motion path.
- Uses bridge receipt time for event-driven motion latching and checks expiry from the monitor loop so `motion=2` no longer depends on a later UI or API poll.

### 4.2.1

- Fixes Home Assistant per-camera feed defaults so explicit `CAM_OPTIONS` `HD` and `SD` values apply at runtime even when `/config/wyze_camera_settings.json` is absent.
- Fixes the bundled Home Assistant native `go2rtc` sidecar so it no longer keeps the upstream default WebRTC listener on `:8555`, which blocked Frigate startup on shared Home Assistant hosts.
- Normalizes preserved `/config/go2rtc_wyze.yaml` listener blocks on startup so stale `api`, `rtsp`, or `webrtc` settings cannot silently bring the `:8555` conflict back.

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
- The `4.2.4` follow-up closes the remaining Home Assistant precedence gap: explicit add-on `CAM_OPTIONS` `HD` and `SD` booleans now also beat stale saved per-camera values, and a native-selected SD feed no longer creates a competing bridge-managed `-sub` path.
- The `4.2.5` follow-up also refreshes preserved native `go2rtc` Wyze aliases from the live helper output on every startup, so stale helper URLs do not keep a camera like `north-yard` pinned to an old producer address after the box or camera IP changes.
- The March 29, 2026 `4.2.1` release also fixes a Home Assistant Frigate startup conflict: the bundled native `go2rtc` sidecar now disables its default WebRTC listener so it no longer silently grabs host port `8555`.
- The current `4.2.2` follow-up hardens MQTT motion semantics for Home Assistant and Scrypted workflows: the BOA/LAN motion path now publishes on the correct `wyzebridge/<camera>/motion` topic with the same `1`/`2` payload contract as the API motion path, and event-driven motion expiry now uses bridge receipt time plus a deterministic monitor-loop expiry check so `motion=2` does not depend on a later UI/API poll.
- On the March 29, 2026 validation host, the follow-up Frigate CPU tuning also validated a safe live pattern for non-Wyze Scrypted cameras: keep record-only cameras out of detect, split active detect cameras onto Scrypted rebroadcast main/sub inputs (`record` on main, `detect` on sub), and if the HA host is an Intel N100 class box, prefer camera-scoped Frigate `preset-vaapi` enablement on only the proven active detect cameras instead of a blanket global hwaccel switch.
- On the March 29, 2026 validation host, a later Scrypted HKSV repair pass confirmed that Wyze MQTT motion cameras can fail for different per-camera reasons even when the MQTT path is shared. `HAMSTER` needed both `HomeKit -> RTP Sender = Scrypted` and `Streams -> RTSP Parser = FFmpeg (TCP)`. `South Yard` first needed `HomeKit -> RTP Sender = Scrypted`, but that alone only got Scrypted to finish the motion-recording session; HomeKit still did not keep a clip. A deeper live compare against working `Deck` showed `South Yard` was the odd `h264/aac` path with unset/non-monotonic timestamp warnings, while `Deck` was `h264/pcm_s16be`. The follow-up live fix for `South Yard` enabled both `HomeKit -> Transcode Audio` and `HomeKit -> Transcode Video`, which removed the visible timestamp warnings from the HomeKit recording path while preserving successful `motion recording finished` logs.
- A later live isolation pass created a fresh `South Yard 2` RTSP clone to separate stream problems from trigger problems. The clone used the same `south-yard-sd` source and could still finish HomeKit recording sessions on the external MQTT/custom-motion path, but the user only saw an actual HomeKit clip after that clone was switched to `OpenCV Motion Detection` and real visual motion. Production `South Yard` was then cleaned up to use OpenCV motion directly, the test clone was deleted, and the dedicated `South Yard Wyze Motion` helper device was removed. A stricter March 30 retest then replayed a fake MQTT `1 -> 2` pulse through rebuilt custom-motion wiring. The final clean result used a fresh dedicated MQTT helper, disabled `OpenCV Motion Detection`, reselected that helper in `Custom Motion Sensor`, and then restarted Scrypted before replaying the pulse. Without the restart, the helper received the MQTT payloads but the camera did not reliably follow them. After the restart, `South Yard` flipped to motion and Scrypted logged `motion recording starting` and `motion recording finished` for the fake pulse. Production was restored to OpenCV afterward, and the investigation handoff is captured in `tasks/docker-wyze-bridge-south-yard-motion-handoff-2026-03-29.md`.

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

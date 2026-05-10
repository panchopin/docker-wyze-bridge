# Docker Wyze Bridge

[![GitHub release (latest by date)](https://img.shields.io/github/v/release/thatdaveguy1/docker-wyze-bridge?logo=github)](https://github.com/thatdaveguy1/docker-wyze-bridge/releases/latest)
[![GHCR Package](https://img.shields.io/badge/ghcr-package-blue?logo=github)](https://ghcr.io/thatdaveguy1/docker-wyze-bridge)
[![Home Assistant Add-on](https://img.shields.io/badge/home_assistant-add--on-blue.svg?logo=homeassistant&logoColor=white)](./docs/user_guide/install_ha.md)

### WebRTC/RTSP/RTMP/HLS Bridge for Wyze Cameras

![Wyze Bridge UI](https://user-images.githubusercontent.com/67088095/224595527-05242f98-c4ab-4295-b9f5-07051ced1008.png)

Create local WebRTC, RTSP, RTMP, and HLS streams for Wyze cameras without custom firmware. This fork focuses on newer Wyze camera behavior, Home Assistant packaging, and the real limitations and runtime behavior validated for the 4.3 release.

- No camera firmware mods required.
- Home Assistant add-on with visible Wyze login fields by default.
- WebRTC/KVS-backed bridge path for modern Wyze models.
- Native Home Assistant `go2rtc` RTSP sidecar on `:19554` for supported 4.3 workflows.

## 4.3 Highlights

- Home Assistant API snapshot mode now avoids slow RTSP snapshot attempts and uses the fast Wyze thumbnail path instead.
- `-sub` thumbnail requests can fall back to the base camera thumbnail, which helps Scrypted/HomeKit-style consumers that ask for substream image names.
- Native `go2rtc` V4 metadata now covers the validated SD alias as well as the main alias.
- Advanced Home Assistant users can set `GO2RTC_LAN_IP_OVERRIDES` when Wyze helper URLs keep a stale LAN address after DHCP changes; no private LAN overrides are built in.
- The late 4.2 WHEP and MediaMTX stability fixes are included in this release line, reducing stuck no-media sessions and port conflicts on shared Home Assistant hosts.

## 4.2 Highlights

- Home Assistant and root Docker runtimes now share the same native `go2rtc` bootstrap path, with the supported RTSP sidecar surface on `:19554`.
- Camera metadata, `/health/details`, and the Web UI now expose per-camera native-vs-bridge selection plus granular `HD` and `SD` feed publishing controls.
- `frontend.py`, `site.js`, and `index.html` are normalized across the three runtime trees where behavior should match, while preserving the intentional dev add-on `:55000` talkback loopback port.
- API-first native talkback remains limited to native-selected cameras, with uploaded-audio talkback validated on native-selected V4 paths.
- Public docs and add-on/package version surfaces are aligned for the `4.2.9` release; `4.3.0` adds the Home Assistant snapshot and native V4 follow-up fixes above.

## 4.2 Patch Releases

### 4.2.9

- Fixes the native `go2rtc` startup race that could make native-only cameras look offline after every bridge restart when alias readiness lagged behind the sidecar API coming up.
- Keeps `native_alias_ready` as a diagnostic signal, but no longer lets that transient startup state block native RTSP URL assignment or camera selection.
- Hardens the Home Assistant `4.2.9` validation path for the current host by honoring configured MediaMTX listener addresses from env and completing a 20-minute soak on the validated HLS reroute when `58888` was already occupied on-box.

### 4.2.8

- Stops the Home Assistant WHEP proxy from retrying forever when `/kvs-config/<camera>` reports `404 camera [x] not found`, so removed or unpublished bridge paths stop churning logs.
- Stops reusing stale startup-only WHEP sessions that never reached audio/video readiness, so bridge-managed substreams like `deck-sub` and `garage-sub` can be recreated cleanly instead of getting stuck behind dead `upstream_state="new"` sessions.
- On the live validation host, `deck-sub`, `garage-sub`, `south-yard-sub`, and `hamster` all settled back into connected audio/video paths, and the final bridge/Scrypted/Frigate log sweep cleared the old `400 Bad Request` / `503` churn.

### 4.2.7

- Fixes Home Assistant `HL_CAM3P` SD-only routing so validated native `go2rtc` `-sd` feeds can stay available even when the bridge-managed `-sub` path is intentionally absent or unreliable.
- Keeps ordinary V3-class substreams on the established bridge WebRTC/KVS path instead of broadly forcing them onto the TUTK fallback, while still letting `HL_CAM3P` and `HL_CAM4` take the special-case paths that were actually validated.
- Keeps Home Assistant `/api` and the Web UI camera catalog populated even when a camera's only enabled feed is native-only, and makes those native-selected cards advertise the real `:19554` RTSP target instead of a misleading bridge URL.

### 4.2.6

- Fixes the remaining Home Assistant ingress asset-path gap by switching the last hardcoded Web UI JavaScript includes to ingress-aware `url_for('static', ...)` calls, including the dedicated `/webrtc/<camera>` page.
- Makes the native `go2rtc` sidecar alias refresh follow the bridge's live published `/api` catalog when available, so disabled or filtered cameras and unsupported `HL_BC` HD feeds are no longer prepared as native aliases just because `/api/wyze` returned a helper URL.

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
| Wyze Cam V3 Pro | Bridge WebRTC/KVS | Validated up to `2560x1440` | Supported on firmware `4.58.0+`; a bridge `-sub` alias is not proof of a true low-bandwidth split on every install | On the Home Assistant validation host, the native `go2rtc` `-sd` alias reached `640x360` while bridge-managed `-sub` remained unreliable |
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
- On the April 2, 2026 validation host, the production Home Assistant Wyze Bridge add-on also revalidated that same native-sidecar path live: once startup finished refreshing `go2rtc_wyze.yaml`, native aliases were present again for `hamster-sd`, `deck-sd`, `garage-sd`, `back-yard-sd`, `south-yard-sd`, and `north-yard`. Repointing Frigate's record-only Wyze cameras from bridge `:58554/*-sub` inputs to those native `:19554/*-sd` aliases restored `hamster` and reduced observed Frigate full-system CPU from roughly `52-54%` down to about `44-45%` on the same HA box.
- The same April 2, 2026 live pass finished the SD-only cleanup for production Frigate too: after the production bridge stopped publishing the old `north-yard` main path, Frigate `north_yard` was updated from the stale bridge `:58554/north-yard` source to the native `:19554/north-yard-sd` alias. Post-restart validation showed `north_yard` back at `5 fps` with fresh snapshots, while Frigate full-system CPU stayed in the same improved mid-40% range.
- On the April 3, 2026 validation host, a follow-up live Scrypted audit reconfirmed the current Wyze/HomeKit production shape. `Garage`, `Deck`, `North Yard`, and `HAMSTER` all stayed healthy on MQTT-backed custom motion helpers and were re-tested live with fake broker `motion 1 -> 2` publishes that drove both helper and camera `motionDetected` state plus fresh Scrypted `motion recording starting` / `motion recording finished` logs. `North Yard` and `HAMSTER` also stayed on the repaired native `:19554/*-sd` RTSP sources with `FFmpeg (TCP)` parsing, while `South Yard` remained intentionally on `OpenCV Motion Detection` and still logged successful transcoded HomeKit motion recordings on its current `south-yard-sub` source.
- On the April 4, 2026 validation host, `Back Yard` was added back into the same Scrypted Wyze MQTT motion pattern used by the other working HomeKit Wyze cameras. The live camera now carries `Custom Motion Sensor`, points at dedicated helper `Back Yard Wyze Motion`, keeps `HomeKit -> RTP Sender = Scrypted`, and after a Scrypted restart responded to fake broker publishes on `wyzebridge/back-yard/motion` with both helper and camera `motionDetected false -> true -> false`. That restores the motion-trigger path needed before enabling HomeKit recording for `Back Yard`.
- On the March 29, 2026 validation host, a later Scrypted HKSV repair pass confirmed that Wyze MQTT motion cameras can fail for different per-camera reasons even when the MQTT path is shared. `HAMSTER` needed both `HomeKit -> RTP Sender = Scrypted` and `Streams -> RTSP Parser = FFmpeg (TCP)`. `South Yard` first needed `HomeKit -> RTP Sender = Scrypted`, but that alone only got Scrypted to finish the motion-recording session; HomeKit still did not keep a clip. A deeper live compare against working `Deck` showed `South Yard` was the odd `h264/aac` path with unset/non-monotonic timestamp warnings, while `Deck` was `h264/pcm_s16be`. The follow-up live fix for `South Yard` enabled both `HomeKit -> Transcode Audio` and `HomeKit -> Transcode Video`, which removed the visible timestamp warnings from the HomeKit recording path while preserving successful `motion recording finished` logs.
- A later live isolation pass created a fresh `South Yard 2` RTSP clone to separate stream problems from trigger problems. The clone used the same `south-yard-sd` source and could still finish HomeKit recording sessions on the external MQTT/custom-motion path, but the user only saw an actual HomeKit clip after that clone was switched to `OpenCV Motion Detection` and real visual motion. Production `South Yard` was then cleaned up to use OpenCV motion directly, the test clone was deleted, and the dedicated `South Yard Wyze Motion` helper device was removed. A stricter March 30 retest then replayed a fake MQTT `1 -> 2` pulse through rebuilt custom-motion wiring. The final clean result used a fresh dedicated MQTT helper, disabled `OpenCV Motion Detection`, reselected that helper in `Custom Motion Sensor`, and then restarted Scrypted before replaying the pulse. Without the restart, the helper received the MQTT payloads but the camera did not reliably follow them. After the restart, `South Yard` flipped to motion and Scrypted logged `motion recording starting` and `motion recording finished` for the fake pulse. Production was restored to OpenCV afterward, and the investigation handoff is captured in `tasks/docker-wyze-bridge-south-yard-motion-handoff-2026-03-29.md`.

## Documentation

- [4.2 Release Notes](./docs/user_guide/release_notes_v4.md)
- [Camera Support and Limits](./docs/user_guide/camera_support.md)
- [Home Assistant Add-on Docs](./home_assistant/DOCS.md)
- [Troubleshooting Guide](./docs/user_guide/troubleshooting.md)
- [Upgrade Guide](./docs/user_guide/upgrade.md)

## Operational Notes

- On the April 12, 2026 Home Assistant host audit, the HA core and LAN frontend remained healthy while the active remote path was a Cloudflare Access-protected hostname and Home Assistant's saved internal/external URLs still pointed at an older DuckDNS address. If the companion app shows a generic connection failure in this state, check URL drift and remote-auth gates before treating it as a server outage.
- The same April 12 follow-up fixed that mismatch by setting Home Assistant `internal_url` to `http://192.168.1.244:8123` for LAN use and `external_url` to `https://ha.tokentradegames.com` for remote use through Cloudflare Access.
- A separate April 12 Frigate outage on the same host turned out to be a stale Supervisor media-mount problem rather than bad Frigate camera config. Reloading the `frigate` network mount and then starting the add-on restored Frigate to a healthy `started` state with live `/api/stats` camera fps again.
- A later April 12 Frigate live-view follow-up confirmed the stable production pattern for the driveway cameras on this host: keep the direct HD `record` and SD `detect` ffmpeg inputs, and add persisted `go2rtc` HD live streams only for `south_driveway` and `north_driveway`. A 15-minute soak with both live streams held open stayed around `10 camera_fps`, `10 process_fps`, and `0 skipped_fps`, while fresh recording segments remained `2560x1440`.
- Use `scripts/ha_frigate_reliability.sh` for a repeatable live audit of Frigate add-on state, per-camera fps health, go2rtc stream presence, and recent watchdog/timestamp/AAC log issues from the Home Assistant host.
- On the April 14, 2026 HomeKit instability pass, the main production failure was a bridge-side startup bug in the native `go2rtc` sidecar rather than a Scrypted or HomeKit transport outage. In the SD-only production setup, the authenticated bridge `/api` camera catalog could be empty during startup, and the sidecar treated that empty catalog as authoritative enough to rewrite `/addon_configs/0eb0428f_docker_wyze_bridge_v4/go2rtc_wyze.yaml` with an empty `streams:` block. That made native `:19554/*-sd` URLs return `404 Not Found` in Scrypted. Falling back to explicit `/api/<camera>/stream-config` feed flags when the catalog is empty restored the live alias table on rebuild and brought `deck-sd`, `garage-sd`, `back-yard-sd`, and `north-yard-sd` back. `HAMSTER` remained a separate camera-specific native-path follow-up after the alias-table repair.
- A later April 14, 2026 Hamster/South Yard follow-up closed the remaining household outage without changing the healthy South Yard path. `South Yard` stayed on `rtsp://192.168.1.244:58554/south-yard-sub` and continued probing cleanly at `640x360`. `HAMSTER`'s remaining break was not in Scrypted or HomeKit itself but in the bridge's native-selection logic and current live options: production `CAM_OPTIONS` still forced `HAMSTER` to SD-only, which kept Scrypted pointed at dead native `rtsp://192.168.1.244:19554/hamster-sd` even after the alias table was repaired. The immediate live fix was to flip only the `HAMSTER` Supervisor option entry to `HD=true`, `SD=false`, and `STREAM=main`, restart the production bridge, verify `rtsp://192.168.1.244:58554/hamster` at `2560x1440` while `hamster-sd` still returned `404`, and then update Scrypted device `223` to use the working bridge URL. Fresh bridge logs then showed Scrypted reconnecting to `/hamster`.
- The same April 14, 2026 wrap-up also closed the last live bridge-side churn in the bundled `whep_proxy`. Two separate bugs were involved: reconnect loops treated bridge `/kvs-config/<camera>` `404 camera [x] not found` responses as retryable, and stale startup sessions with `upstream_state="new"` plus no media were considered reusable forever. `4.2.8` makes the `404` refresh failure terminal, only reuses no-media sessions during a short startup grace window, and the live retest brought `deck-sub`, `garage-sub`, `south-yard-sub`, and `hamster` back to connected audio/video with no matching bridge, Scrypted, or Frigate errors in the final log sweep.

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

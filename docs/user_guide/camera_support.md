# Camera Support and Limits

This guide documents the current public `4.2` behavior for the camera models that received the deepest validation in this release cycle.

Two important rules:

- `main` and `substream` describe useful published feeds, not just whether a URL alias exists.
- A camera can support a `-sub` alias and still return the same resolution as the main stream. Wyze-side firmware decides the final output.

## Support Matrix

| Model | Bridge main | Bridge substream | Home Assistant native `go2rtc` RTSP (`:19554`) | Current public limit |
| :--- | :--- | :--- | :--- | :--- |
| Wyze Cam V3 (`WYZE_CAKP2JFUS`) | Supported | Supported on firmware `4.36.10+` | Available, but not the primary documented path for `4.2` | Validated V3-class bridge paths have reached `1920x1080` for both main and substream. Higher output is not promised. |
| Wyze Cam V3 Pro (`HL_CAM3P`) | Supported | Supported on firmware `4.58.0+` | Available, but no public `4.2` improvement over the standard bridge path is claimed | Validated main stream reached `2560x1440`. `4.2` does not promise a fixed native or substream ceiling for every installation. |
| Wyze Cam V4 (`HL_CAM4`) | Supported, but standard bridge RTSP can remain `640x360` on some KVS/WebRTC paths | Exposed by the bridge, but not a reliable high/low split in `4.2` | Supported Home Assistant feature in `4.2` | Validated Home Assistant native `go2rtc` path reached `2560x1440` main and `640x360` substream. TUTK fallback is not a reliable way to recover higher RTSP resolution. |
| Wyze Bulb Cam (`HL_BC`) | Supported | No validated distinct substream in `4.2` | Supported surface exists, but no validated quality gain over the bridge path is claimed | Public `4.2` validation kept both main and `-sd` feeds at `640x360`. No software-only 2K path has been validated. |

## Model Notes

### Wyze Cam V3

- The fork routes V3 cameras through the modern WebRTC/KVS-backed path by default.
- Bridge substream support depends on camera firmware support; the current capability gate is `4.36.10+`.
- `QUALITY` and `SUB_QUALITY` can influence the request the bridge makes, but they do not override the resolution the camera actually emits.

### Wyze Cam V3 Pro

- V3 Pro remains one of the strongest standard-bridge outcomes in the current codebase.
- The public `4.2` docs only claim the validated main-stream ceiling of `2560x1440`.
- Native `go2rtc` is included in the Home Assistant add-on, but `4.2` does not promise a better V3 Pro result than the standard bridge path.

### Wyze Cam V4

- V4 is the main reason `4.2` now documents the native Home Assistant `go2rtc` sidecar explicitly.
- Standard bridge RTSP can still remain `640x360` even when the camera itself is higher resolution.
- The supported Home Assistant native sidecar path on `:19554` is the best documented RTSP path for validated V4 installs in this release.
- The internal sidecar API on `:11984` is not part of the stable public interface.

### Wyze Bulb Cam

- Bulb Cam is compatible with the modern RTC/WHEP path and remains supported.
- The important limitation discovered in `4.2` is that compatibility does not equal high-resolution RTSP.
- Current public validation keeps both the bridge path and the Home Assistant native sidecar path at `640x360`.

## General Limits That Apply Across Models

- `QUALITY` settings are requests, not guarantees.
- A working `-sub` alias does not guarantee a lower-resolution helper feed.
- Wyze firmware and cloud signaling can constrain the final KVS/WebRTC resolution independently of the bridge.
- The Home Assistant sidecar API on `:11984` is internal and can change without notice.

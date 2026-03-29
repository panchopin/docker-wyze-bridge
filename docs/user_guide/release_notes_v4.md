# Release Notes 4.2

`4.2` is a cleanup and usability release.

The short version:

- The app and add-on builds are now more consistent with each other.
- The Web UI makes it much clearer which camera feeds are actually available.
- Home Assistant support for the native `go2rtc` RTSP path is still included.
- The docs now describe what really works today, in much plainer terms.

## Planned 4.2.1 Follow-up

This repository also includes an unreleased `4.2.1` patch candidate.

- Home Assistant now treats explicit per-camera `CAM_OPTIONS` `HD` and `SD` values as the runtime default feed state.
- That means an `SD`-only camera setup no longer depends on a hidden `/config/wyze_camera_settings.json` file just to match the visible add-on config.
- The fix was validated in the dev add-on with the runtime settings file removed, then production was restored with the intended `SD`-only defaults.

## Biggest Changes

### Easier feed controls in the Web UI

- You can now choose `HD` and `SD` feeds per camera more clearly.
- You can set separate bitrate targets for each feed.
- If a camera does not really support a feed, that option stays disabled instead of pretending it should work.
- The UI also shows the feed path and the resolution the app currently knows about.

### More consistent behavior across builds

- The main app, the Home Assistant add-on, and the local dev add-on now share the same frontend behavior where they should.
- That means fewer surprises when moving between environments.
- The one intentional difference that stays is the local dev add-on's internal talkback loopback port.

### Better Home Assistant support

- The Home Assistant add-on still includes the native `go2rtc` RTSP option.
- The supported native RTSP address is still `:19554`.
- The internal API on `:11984` is still internal-only and should not be treated like a stable public feature.

### Fewer startup edge-case failures

- Startup is a little more defensive now.
- The bridge is better about not exposing downstream output before upstream media is actually ready.
- It is also less likely to fall over during startup if Wyze account profile details come back incomplete.

### Clearer docs

- The docs now focus more on real-world results and less on ideal-case promises.
- Camera limits are spelled out by model.
- The product name stays simply `Docker Wyze Bridge`.

## What To Expect By Camera Model

| Model | Plain-English summary |
| :--- | :--- |
| Wyze Cam V3 | Still one of the safer bets. The bridge path is the main documented option, and tested V3-class results have reached `1920x1080`. |
| Wyze Cam V3 Pro | Can do better than V3 in the main stream. Tested results reached `2560x1440`, but substream results can still vary by setup. |
| Wyze Cam V4 | The normal bridge path can still get stuck at `640x360`. In Home Assistant, the native `go2rtc` path is the best-documented way to get the better tested result: `2560x1440` main and `640x360` substream. |
| Wyze Bulb Cam | Supported, but still limited in practice. Current tested results keep both main and `-sd` at `640x360`. |

For the detailed support table, see [Camera Support](./camera_support.md).

## Important Limits

- A setting like `QUALITY` is a request, not a guarantee.
- Some cameras expose a `-sub` path without giving you a truly different lower-resolution stream.
- A camera being "supported" does not automatically mean it will deliver its advertised maximum resolution through every path.

## Attribution

This release continues to build on work from:

- `idisposable/docker-wyze-bridge`
- `akeslo/docker-wyze-bridge`
- `kroo/wyzecam`
- `aler9/mediamtx`
- `AlexxIT/go2rtc`

The bundled Home Assistant native sidecar uses `go2rtc` from `AlexxIT/go2rtc`, licensed under MIT. See [THIRD_PARTY_NOTICES.md](../../THIRD_PARTY_NOTICES.md).

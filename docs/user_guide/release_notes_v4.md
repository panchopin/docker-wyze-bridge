# Release Notes 4.3

## 4.3.5 Release

`4.3.5` is a narrow native-SD durability patch for the `4.3` release line.

- The Home Assistant go2rtc sidecar now respects explicit per-feed bridge config when it builds native aliases, so a camera configured with `HD=false` and `SD=true` no longer seeds a competing fake HD alias alongside the real `-sd` alias.
- Native snapshot refresh now forces one fresh re-preload attempt when the selected native alias has gone stale, which helps the bridge recover from the split-brain case where go2rtc still has producer metadata but `frame.jpeg` is no longer returning a real JPEG.
- The regression coverage now locks both behaviors in place: SD-only alias generation stays honest, and stale selected native aliases get a single forced warm-up retry before fallback.

## 4.3.3 Release

`4.3.3` is a narrow SD-only native-feed reliability patch for the `4.3` release line.

- Native `go2rtc` stream diagnostics now fall back from the fast per-alias probe to the full stream table when the fast probe times out or returns invalid data.
- SD-only setups can keep a working `*-sd` alias selected when `go2rtc` is already producing that stream, instead of falling back to a dead main/KVS route because one readiness probe was slow.
- Snapshot paths that depend on a stable RTSP/prebuffer feed benefit from the same alias stability, especially when the still image is captured from the SD stream rather than forced through a fresh snapshot request.
- The regression test covers the slow per-alias probe case and proves the full stream table can still mark the SD alias alive.

## 4.3.2 Release

`4.3.2` is a Home Assistant stability and release-hygiene patch for the `4.3` release line.

- Startup readiness now waits for the authenticated camera catalog and semantic `/api/ready` state before publishing ready, which prevents empty boot-time catalogs from clearing native `go2rtc` aliases.
- Snapshot refresh now validates content rather than trusting status codes or mtimes: empty, tiny, non-image, stale, and byte-identical frames are rejected before they replace cached stills.
- `SD_ONLY=true` is now a hard Home Assistant mode. Production proof covers one SD feed per camera, HD controls and HD enable paths rejected or hidden, and only `*-sd` native aliases exposed by `go2rtc`.
- The WHEP proxy now keeps recently healthy streams in a bounded recovering state during short reconnect windows, while still expiring and recreating streams that fail to recover media.
- The runtime overlay build is now the packaging source of truth, with release hygiene checks that keep local agent notes, scratch files, option payloads, SSH env files, and private SDK values out of public artifacts.
- Current live proof is intentionally scoped: Phase 1 snapshots, Phase 2 startup/API, Phase 3 SD-only, and Phase 5 overlay/API pass. The strict one-hour Phase 4 gate remains red because Frigate/Scrypted skipped-FPS blips occurred even while WHEP media stayed ready.

## 4.3.1 Release

`4.3.1` is the preview-integrity and snapshot-refresh follow-up for the `4.3` release line.

- Cached preview files are now validated as real images before the bridge serves them. That blocks zero-byte files, HTML/login pages accidentally saved with `.jpg` names, and the vertical-smear corruption that can appear in bad still frames.
- Thumbnail refreshes now take the stronger path through `refresh_preview()`: first try a fresh native `go2rtc` or RTSP snapshot, restart a stuck stream once if needed, and only then fall back to a recent valid Wyze API thumbnail.
- Native `go2rtc` snapshots now wait for a genuinely new frame instead of accepting `503`, empty, invalid, or unchanged bytes, and cached API thumbnails are only reused when they are still recent and valid.
- Web UI preview metadata now prefers the freshest valid main or `-sub` preview image, and `/health/details` now includes `go2rtc` plus WHEP log tails so snapshot failures are easier to diagnose.
- Home Assistant startup now cleans stale `whep_proxy` loops before relaunching the proxy, preventing orphaned helpers from hanging onto the local bind across rebuilds.

## 4.3.0 Release

`4.3.0` is a Home Assistant reliability release for snapshots, native `go2rtc`, and the late 4.2 streaming hardening work.

- API snapshot mode now serves `/snapshot/<camera>.jpg` through the fast Wyze thumbnail path instead of making a slower RTSP snapshot attempt.
- Thumbnail requests for `-sub` stream names can fall back to the base camera thumbnail when Wyze only exposes the primary camera image.
- V4 native `go2rtc` metadata now treats the validated SD alias as selected when the sidecar is reachable.
- Users who need to correct stale Wyze helper LAN addresses can opt in with `GO2RTC_LAN_IP_OVERRIDES=MAC=host,MAC=host`; the release does not ship any private LAN overrides.
- The WHEP and MediaMTX fixes from the end of the 4.2 line are included, reducing stuck no-media startup sessions and shared-host port conflicts.

`4.2` is a cleanup and usability release.

The short version:

- The app and add-on builds are now more consistent with each other.
- The Web UI makes it much clearer which camera feeds are actually available.
- Home Assistant support for the native `go2rtc` RTSP path is still included.
- The docs now describe what really works today, in much plainer terms.

## 4.2.9 Patch Release

`4.2.9` is the native startup-race and Home Assistant validation follow-up for the `4.2` release line.

- Native-only camera selection no longer depends on `_native_alias_is_ready()`, which was only a transient startup probe and could briefly report `False` while `go2rtc` was already reachable.
- `native_alias_ready` stays available as a diagnostic field, but it no longer blocks native RTSP URL assignment, camera-catalog selection, or the HomeKit/Scrypted path that depends on those values.
- Matching regression coverage now locks in both sides of the rule: a reachable `go2rtc` API keeps native selection active even before the alias is hot, while a fully unreachable sidecar still reports the camera as not selected.
- On the live Home Assistant validation host, the cleaned `ssltest` add-on completed a 20-check soak with `mtx_alive=true`, `wyze_authed=true`, RTSP/WebRTC/native ports answering, and the old `SSLCertVerificationError` / `.email` startup crashes absent. The host already had something else bound to `:58888`, so the validation soak used a temporary HLS listener on `:39888` instead.

## 4.2.8 Patch Release

`4.2.8` is the Home Assistant WHEP stability follow-up for the `4.2` release line.

- The bundled `whep_proxy` now treats `/kvs-config/<camera>` `404 camera [x] not found` as a terminal refresh failure instead of reconnecting forever.
- WHEP startup sessions are only reused while they are fresh or once media is actually flowing, so stale `upstream_state="new"` sessions with no audio/video are replaced instead of wedging future readers.
- Matching Go coverage now locks in the terminal-refresh and stale-session rules in both Home Assistant WHEP proxy trees.
- On the live Home Assistant validation host, `deck-sub`, `garage-sub`, `south-yard-sub`, and `hamster` all returned to connected audio/video state, and the final bridge/Scrypted/Frigate log sweep cleared the old `400 Bad Request` / `503` churn.

## 4.2.7 Patch Release

`4.2.7` is the Home Assistant V3 Pro SD-feed follow-up for the `4.2` release line.

- Home Assistant `HL_CAM3P` SD-only setups now prefer the validated native `go2rtc` `-sd` alias instead of exposing a misleading or broken bridge-managed `-sub` path.
- The native alias refresh helper now keeps native-only feeds even when they are intentionally absent from the bridge's live published stream catalog.
- Ordinary V3-class substreams stay on the established bridge WebRTC/KVS path instead of being broadly rerouted through the TUTK fallback.
- On the live Home Assistant validation host, the V3 Pro `-sd` alias became readable again at `640x360` on `:19554`, and the Frigate `hamster` camera was cut over to that feed.

## 4.2.6 Patch Release

`4.2.6` is the ingress-finish and native-alias correctness follow-up for the `4.2` release line.

- The last hardcoded Web UI JavaScript includes now use ingress-aware `url_for('static', ...)` calls, including the dedicated `/webrtc/<camera>` page.
- Focused frontend regression coverage now locks in ingress-prefixed JavaScript URLs on both the main page and the dedicated WebRTC page.
- `webrtc.js` now refreshes signaling from the root-relative `/signaling/<camera>` path instead of resolving a broken nested `/webrtc/signaling/...` URL.
- The native `go2rtc` sidecar now waits for the authenticated bridge `/api` surface before it trusts bridge state.
- Native alias prep now follows the bridge's live published camera catalog, so filtered cameras and unsupported `HL_BC` HD feeds are skipped instead of being prepared just because the helper returned a URL.
- On the live Home Assistant validation host, the styled ingress page came back and the sidecar kept only the expected aliases: `deck-sd`, `garage-sd`, `hamster-sd`, `north-yard`, and `south-yard-sd`.

## 4.2.5 Patch Release

`4.2.5` is the native alias refresh follow-up for the `4.2` release line.

- Preserved `go2rtc_wyze.yaml` aliases are now refreshed from the current `/api/wyze` helper output at startup instead of being frozen just because the config file already contains seeded aliases.
- The runtime images now include `curl`, which the sidecar refresh helper needs in the running add-on to talk to its own local `go2rtc` API.
- On the live Home Assistant validation host, this rewrote North Yard from the stale `192.168.1.176` helper URL to the current `192.168.1.185` helper URL.
- After that refresh, both `north-yard` and `north-yard-sd` became active native producers again on `:19554`.

## 4.2.4 Patch Release

`4.2.4` is the Home Assistant feed-selection correctness follow-up for the `4.2` release line.

- Explicit Home Assistant `CAM_OPTIONS` `HD` and `SD` booleans now override stale saved per-camera feed settings in `/config/wyze_camera_settings.json`.
- Native-selected SD feeds no longer create a competing bridge-managed `-sub` path.
- This specifically removes the stray `north-yard-sub` bridge startup path when `NORTH YARD` is configured with `SD=false`.
- Focused regression coverage now locks in both the precedence rule and the bridge-substream skip for native SD feeds.

## 4.2.2 Patch Release

`4.2.2` is the MQTT motion hardening follow-up for the `4.2` release line.

- Fix the BOA/LAN motion publish path so MQTT uses the correct `wyzebridge/<camera>/motion` topic instead of a doubled prefix.
- Normalize BOA/LAN motion payloads to `1` and `2` so they match the API motion contract already expected by Home Assistant and Scrypted helpers.
- Use bridge receipt time for cloud/API motion latching instead of the original event timestamp so motion windows stay predictable.
- Check motion expiry from the monitor loop so `motion=2` is published deterministically instead of waiting for a later status read.
- Add focused regression coverage for BOA topic shape, BOA payload shape, receipt-time latching, and deterministic expiry checks.

## 4.2.1 Patch Release

`4.2.1` is the follow-up patch for the `4.2` release line.

- Home Assistant now treats explicit per-camera `CAM_OPTIONS` `HD` and `SD` values as the runtime default feed state.
- That means an `SD`-only camera setup no longer depends on a hidden `/config/wyze_camera_settings.json` file just to match the visible add-on config.
- The fix was validated in the dev add-on with the runtime settings file removed, then production was restored with the intended `SD`-only defaults.
- The bundled Home Assistant native `go2rtc` sidecar now writes an explicit `webrtc.listen` override so it does not keep upstream's default `8555` listener and block Frigate from starting on the same host.
- Preserved `/config/go2rtc_wyze.yaml` files are also normalized on startup so an older listener block cannot quietly reintroduce the `8555` conflict after rebuilds.

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
| Wyze Cam V3 Pro | Can do better than V3 in the main stream. Tested results reached `2560x1440`, and the Home Assistant native `-sd` alias now validates at `640x360` on the release host. Bridge `-sub` behavior can still vary by setup. |
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

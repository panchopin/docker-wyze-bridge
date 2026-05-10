# What's Changed

## What's Changed in v4.3.0

Release focused on Home Assistant snapshot reliability and native `go2rtc` follow-up fixes.

### Major Changes

- In API snapshot mode, Home Assistant `/snapshot/<camera>.jpg` requests now use the fast Wyze API thumbnail path instead of forcing an RTSP/ffmpeg snapshot attempt.
- `/thumb/<camera-sub>.jpg` requests can fall back to the base camera URI when Wyze only exposes a thumbnail for the primary camera name, improving Scrypted/HomeKit-style snapshot consumers.
- Mark `HL_CAM4` native SD aliases as selected when the native sidecar is reachable, matching the validated V4 main/native behavior.
- Replace the private hardcoded LAN helper-address workaround with the optional `GO2RTC_LAN_IP_OVERRIDES` environment variable for users who need to correct stale Wyze helper URLs after DHCP changes.
- Carry forward the late 4.2 WHEP and MediaMTX hardening so stale no-media sessions and shared-host port conflicts are less likely to wedge streams.

## What's Changed in v4.2.9

Patch release fixing a startup race that caused native-only cameras (`north-yard`, `hamster`) to appear offline in HomeKit via Scrypted after every bridge restart.

### Major Changes

- Fix `native_selected` gate in `go2rtc.native_stream_info`: selection is now determined solely by `api_reachable`, not by `_native_alias_is_ready`. The alias-readiness check is a transient startup condition (go2rtc is up but aliases haven't connected yet), and using it to gate `selected` caused `connected=False`/`status="stopped"` in the camera catalog, which Scrypted cached as "camera offline" in HomeKit.
- `native_alias_ready` is preserved as a diagnostic-only field in the returned dict and in `/api/diagnostics` — it still tells you whether the stream is already hot in go2rtc, but a `False` value no longer blocks selection or RTSP URL assignment.
- Apply fix consistently across all three code copies: `app/`, `home_assistant/app/`, and `.ha_live_addon/app/`.
- Live validation on the Home Assistant host also re-proved the startup/auth path with `mtx_alive=true` and `wyze_authed=true` through a 20-check soak. The host already had another service bound to `:58888`, so the validation lane used a temporary HLS listener on `:39888` for that soak instead of the default HLS port.

## What's Changed in v4.2.8

Patch release focused on Home Assistant WHEP proxy stability for bridge-managed RTSP feeds.

### Major Changes

- Treat `/kvs-config/<camera>` `404 camera [x] not found` as terminal inside the bundled `whep_proxy` reconnect loop so removed or unpublished streams stop churning forever.
- Only reuse WHEP upstream sessions that already have media or are still within a short startup window; stale `upstream_state="new"` sessions with no audio/video are replaced cleanly.
- Add focused Go coverage for terminal refresh-config errors and stale-session reuse rules in both the production and dev WHEP proxy trees.
- Validate live on the Home Assistant box that `deck-sub`, `garage-sub`, `south-yard-sub`, and `hamster` all probe cleanly again and that recent bridge/Scrypted/Frigate logs stay clear of the old `400 Bad Request` / `503` errors.

## What's Changed in v4.2.7

Patch release focused on Home Assistant V3 Pro SD-feed correctness.

### Major Changes

- Keep Home Assistant `HL_CAM3P` SD-only setups on the validated native `go2rtc` `-sd` alias instead of a misleading or broken bridge-managed `-sub` path.
- Narrow the special TUTK substream routing so ordinary V3-class substreams stay on the established bridge WebRTC/KVS path.
- Fix the native alias refresh helper so native-only feeds are not dropped just because the bridge's live published `/api` catalog no longer contains a matching bridge stream entry.
- Validate live on the Home Assistant box that `hamster-sd` returns `640x360` on `:19554` and that Frigate can record from that feed after cutover.

## What's Changed in v4.2.6

Patch release focused on the last Home Assistant ingress asset-path gap and on keeping native `go2rtc` aliases aligned with the bridge's live published feeds.

### Major Changes

- Switch the remaining hardcoded Web UI JavaScript includes to ingress-aware `url_for('static', ...)` calls, including the dedicated `/webrtc/<camera>` page.
- Add focused frontend regression coverage for ingress-prefixed JavaScript asset URLs and for the root-relative signaling refresh path used by `webrtc.js`.
- Make the native `go2rtc` sidecar wait for the authenticated bridge `/api` surface instead of trusting `/health` alone.
- Filter native alias prep against the bridge's live published camera catalog so disabled or filtered cameras and unsupported `HL_BC` HD feeds are skipped instead of being seeded just because `/api/wyze` returned a helper URL.
- Validate live on the Home Assistant box that the ingress page loads styled again and that the sidecar keeps only the expected active aliases (`deck-sd`, `garage-sd`, `hamster-sd`, `north-yard`, and `south-yard-sd`).

## What's Changed in v4.2.5

Patch release focused on refreshing preserved native Wyze aliases on Home Assistant hosts.

### Major Changes

- Refresh preserved `go2rtc_wyze.yaml` Wyze aliases after startup instead of returning early just because seeded aliases already exist.
- Install `curl` in the runtime images so the sidecar refresh helper can actually reach the local `go2rtc` API from the running add-on.
- Validate in the Home Assistant dev add-on that North Yard aliases are rewritten from the stale `192.168.1.176` helper URL to the live `192.168.1.185` helper URL and that `rtsp://...:19554/north-yard(-sd)` becomes readable again.

## What's Changed in v4.2.4

Patch release focused on Home Assistant feed-selection correctness for native-selected cameras.

### Major Changes

- Let explicit Home Assistant `CAM_OPTIONS` `HD` and `SD` booleans override stale saved per-camera feed settings in `/config/wyze_camera_settings.json`.
- Stop creating a competing bridge-managed `-sub` path when the SD feed is native-selected.
- Add focused regression coverage for env-over-saved precedence and for skipping bridge substream creation when SD is routed through the native sidecar.
- Validate live in the Home Assistant dev add-on that `north-yard-sub` is no longer created when `NORTH YARD` is configured with `SD=false`.

## What's Changed in v4.2.2

Patch release focused on MQTT motion correctness and deterministic expiry behavior.

### Major Changes

- Fix the BOA/LAN MQTT motion path so publishes land on `wyzebridge/<camera>/motion` instead of the wrong double-prefixed topic.
- Normalize BOA/LAN motion payloads to `1` and `2` so Home Assistant and Scrypted helpers see the same contract as the API motion path.
- Use bridge receipt time for event-driven motion latching instead of the original event timestamp.
- Force motion expiry checks through the stream monitor loop so `motion=2` is published deterministically.
- Add focused regression coverage for topic shape, payload shape, receipt-time latching, and expiry behavior.

## What's Changed in v4.2.1

Patch release focused on Home Assistant defaults, Frigate compatibility, and release-surface cleanup.

### Major Changes

- Fix Home Assistant per-camera feed defaults so explicit `CAM_OPTIONS` `HD` and `SD` values apply at runtime even when `/config/wyze_camera_settings.json` is absent.
- Add focused regression coverage for that precedence rule and validate it live in the dev add-on without a saved runtime settings file.
- Record the production-safe outcome: production restored with the intended `SD`-only camera defaults after validation.
- Fix the bundled Home Assistant native `go2rtc` sidecar so it no longer keeps the upstream default WebRTC listener on `:8555`, which blocked Frigate startup on shared hosts.
- Normalize preserved `/config/go2rtc_wyze.yaml` listener blocks on startup so stale `api`, `rtsp`, or `webrtc` settings cannot keep the old `:8555` bind alive across rebuilds.
- Add packaging regression coverage to ensure the generated sidecar config keeps overriding that default listener in all three runtime trees.

## What's Changed in v4.1.1

Patch release focused on the shared native `go2rtc` runtime path and clearer native camera behavior.

### Major Changes

- Move native `go2rtc` startup into a shared helper so root Docker, the production add-on, and the local dev add-on all bootstrap the same sidecar flow.
- Add camera-level native selection metadata, native snapshot routing, and richer `/health/details` diagnostics so `HL_CAM4` can prefer native while `HL_BC` stays bridge-first.
- Add API-first native talkback through `POST /api/<camera>/talkback` for cameras already validated on the native sidecar path.

## What's Changed in v4.2.0

Release focused on runtime-tree alignment, granular feed publishing controls, and release-surface cleanup.

### Major Changes

- Normalize the shared Web UI runtime across the root app, production add-on, and local dev add-on while preserving the intentional dev-only `:55000` loopback talkback port.
- Carry the merged per-camera feed configuration work across the runtime trees, including `HD` and `SD` enablement, per-feed kbps targets, and surfaced feed metadata in the Web UI.
- Keep the public add-on and docs aligned around the supported native `go2rtc` RTSP surface on `:19554`, with `:11984` still treated as internal-only.
- Bump release and packaging surfaces to `4.2.0` and the dev add-on surfaces to `4.2.0-dev`.

## What's Changed in v4.0.2

Patch release focused on startup hardening and Home Assistant runtime validation.

### Major Changes

- Gate WHEP downstream output tracks on real upstream media readiness instead of local track allocation alone.
- Prevent bridge startup crashes when Wyze login succeeds but `get_user_info` fails or returns empty by falling back to the configured email for local auth/bootstrap needs.
- Add regression coverage for the fallback-user path and keep add-on release metadata aligned for the `4.0.2` patch line.
- Carry forward the minimal Home Assistant prod/dev swap workflow and in-app diagnostics approach used during live validation.

## What's Changed in v4.0.1

Patch release focused on Home Assistant packaging and documentation clarity.

### Major Changes

- Surface the standard Home Assistant login fields (`Wyze email`, `Wyze password`, `Key ID`, `API key`) by default in the add-on manifest.
- Mirror the same visible-login behavior in the repository-local dev add-on manifest and add packaging coverage for it.
- Update HA translations and docs so the standard login path no longer describes the API credentials as optional for normal setup.
- Clarify HA sub-stream wording so it reflects the internal capability map and explicitly notes that Pan V2 is not currently included.
- Validate the current KVS startup and playback behavior in the HA dev lane without changing runtime behavior, since the reported `400` warning was not reproduced in this patch cycle.

## What's Changed in v4.0.0

First public release of the `thatdaveguy1/docker-wyze-bridge` fork. This release focuses on Wyze Cam V4 support, improved Home Assistant integration, and a more stable streaming backend.

### Major Changes

- **Wyze Cam V4 Support:** New cloud-signaled KVS/WebRTC backend for first-class V4 support and improved latency for V3/V3 Pro cameras.
- **Home Assistant Optimized:** New `docker_wyze_bridge_v4` slug, ingress-aware base URLs, and conflict-free port mapping (58554, 58888, 58889).
- **Polished Web UI:** One-click copy buttons for stream URLs, improved protocol status reporting, and better stream availability logic.
- **MediaMTX V1.16.3:** Upgraded backend for lower latency, better WebRTC track gathering, and reduced startup failures.
- **Stability Fixes:** Resolved several long-running session, process-cleanup, and on-demand readiness bugs.

### Credits

This fork builds on the excellent work of:
- `idisposable/docker-wyze-bridge` - Base fork and release line
- `akeslo/docker-wyze-bridge` - KVS/WebRTC signaling and architectural direction
- `kroo/wyzecam` - Fundamental Wyze API and TUTK implementation
- `aler9/mediamtx` - High-performance streaming backend

Attribution is summarized in the credit section below.

## What's Changed in v3.12.3-local

Local patched release built on top of `idisposable/docker-wyze-bridge` `v3.12.3`, with KVS/WebRTC migration ideas likely influenced by `akeslo/docker-wyze-bridge` and a larger set of repo-local reliability, HA integration, and UI work.

### Credit and provenance

- Base fork and release line: `idisposable/docker-wyze-bridge`
- KVS/WebRTC direction for newer cameras, including signaling behavior such as `recipientClientId`: likely influenced by `akeslo/docker-wyze-bridge`
- HA-local packaging, WHEP proxy integration, earlier V4/RTC routing work, deployment tooling, UI changes, regression tests, and operational docs: original local work in this repo
- Detailed attribution was consolidated into this public changelog before release.

### Local changes in this release

- Add a local patched Home Assistant add-on tree under `.ha_live_addon/` with its own Dockerfile, config, runtime, translations, docs, and deployment helpers
- Add a local WHEP proxy path plus KVS config refresh flow for RTC-backed cameras, along with focused routing regression tests
- Fix bridge reliability issues around process cleanup, session lifetime, timeout sizing, and on-demand readiness, with proposed upstream PR notes and targeted tests
- Improve the web UI stream menu, copy actions, protocol availability rules, and loopback auth handling for `/kvs-config/<camera>`
- Add live deployment handoff docs, runbooks, plan docs, task tracking, and sanitized sample payloads used during validation

## What's Changed in v3.12.3

Cleaned up the threading logic around startup/shutdown to reduce CPU and memory leaks

- Added validation checks for the API Key ID and API Key to help prevent issues logging in Fixes #47
- Cleaned up the thread and process tracking to ensure that we release threads when they're done
- Only allow one running purge thread per camera Fixes #40
- Added timeouts to all the thread `.join()`s to ensure we don't hang waiting for threads to die off
- Increased the buffer site for the pipe reads to reduce CPU load
- Consistently swallow ValueError, AttributeError, RuntimeError, and FileNotFound errors so sub-processes and threads terminate correctly

Note: v3.12.2 was everything above, but missing the change notes, oops.

# What's Changed in v3.12.1

Cleaned MQTT logic and pull in some others' changes

### New features

Automatic Sunrise/Sunset snapshots drive ny the `LONGITUDE` and `LATITUDE` configuration variables.
`FORCE_IOTC_DETAIL` if true will force detailed debugging for the IOTC subsystem which can be used to decode a camera's protocol messages.

- MQTT cleanup with more logging and move configuration to config.py
- Read the TUTK device_config.json once not every interaction
- Gathering up other changes
  - Add GW_DBD Doorbell Duo to list not yet validated from @Angel-Vazquez change
  - Add SNAPSHOT_CAMERAS and  sunset/sunrise snapshots from @ruddell [see](https://github.com/mrlt8/docker-wyze-bridge/compare/main...ruddell:docker-wyze-bridge:sunrise-snapshotter
)
  - Picking up the relevant changes from p2pcam
- Cleanup of config circular dependencies
- Fix run if syntax old habits die hard

# What's Changed in v3.12.0

Cleaned up the startup logic to ensure things start quickly and moved configurations around so everything is overrideable

- Moved API-driven snapshots into the `Stream_Manager.py` so they don't delay startup.
- Clean up the /var/log directory in Dockerfile build image
- Better to supply empty, not samples in config
- Switch to `run` for diagnostic dump
- Deprecate the `config.yml` setting of environment variables so we can set the `IMG_DIR` and `RECORD_PATH` reliably even
  if not running inside Home Assistant as an add-on
- Remove the MTX_* variables from the `.env` as we want them to be settable in the options.
- Explicitly default the MTX settings that used to be forced (MTX_READTIMEOUT=30s, MTX_HLSVARIANT=mpegts, MTX_WRITEQUEUESIZE=2048) 
  to ensure backward compatibility
- Updated the defaults for the `IMG_DIR` and `RECORD_PATH` to match what the `.env` would have 
  previously set, but now it's overridable.
- Reduced log spam by making some `.info(` calls `.debug(`
- Don't emit ffmpeg non-error messages  (let the Popen eat them).

## What's Changed in v3.11.1

Turns out you cannot have a completely optional section in a config.yml

Use something like

```yaml
CAM_OPTIONS:
  - CAM_NAME: fake-camera-name
    RECORD: false
```

- Revert CAM_OPTIONS and MEDIAMTX yaml schema and add default values to configs

## What's Changed in v3.11.0

Cleanup of authorization logic and adding background activity

- RECORD **is working again**!
- Marked CAM_OPTIONS and MEDIAMTX as optional in the config
- Cleanup the snapshot pruning to ignore files going missing and
  use only prune each camera's path, not the entire image directory
- Added background pruning of snapshots to speed startup
- Fix forced DEBUG log level
- Fix LOW_LATENCY should be LLHLS
- Extend session connection timeout to 60 seconds
- Fixed FPS calculation
- Split out WyzeStreamOptions
- Split out StreamManager
- Make Stream know type of camera and options.
- Make WyzeStream be a Stream
- Reduced default logging level for ffmpeg
- Tons of logging cleanup
- Cleaned up warnings

## What's Changed in v3.10.14

- Made MQTT config value optional Fixes #39
- Fix MQTT parameters minimum value for bitrate and fps
- Don't emit MQTT state messages unless the state has changed
- Fix warning in  BOA check
- Add missing OFFLINE_TIME and DOMAIN options
- Added documentation of the option defaults.

## What's Changed in v3.10.13

- Fix schema for MQTT discovery messages

## What's Changed in v3.10.12

- Filled out the missing translations and docs
- Fix busted device configuration table (the device.json file had some XML in it)
- Fix bad handling of WYZEDB3 message protocol support
- Clean up wyzecam to adopt original upstream MAIN fixes
- Sync with upstream wysecam DEV branch
- Fix sleep when no data is ready (was waiting 0 seconds instead of the intended 1/80th of a second)
- Yield frame_info in the receive data iterations.
- Decode both FrameInfoStruct OR FrameInfo3Struct and whine if something is wrong.
- Don't discard messages without an expected_response_code as we know what it's supposed to be anyway.
- Proper type, use literals, better logging, eliminate dead code
- Remove exit logging
- Revert type of resend and remove redundant SDK license set
- Add resp so debug structure are visible

## What's Changed in v3.10.11

- Fix errors in startup avClientStartEx doesn't return a tuple
- Fix path construction for MediaMTX
- Fix python lint warnings and a whole lot of logging and type cleanup
- Move environment stuff to config and config reading out of mtx_server
- Don't complain about directories existing in migration
- Attempt to ensure directories for recordings
- Capture stdout of MediaMTX and openssl for logging
- Capture the traceback before context corrupted
- Switched to better logging syntax
- Let's declare the ports we EXPOSE in the Dockerfile(s)

## What's Changed in v3.10.10

- Add camera IP to MQTT message
- Adjust the recording path construction more
- Added STUN_SERVER support
- Switched all home assistant configs to host_network
- Don't default WB_AUTH nor MQTT on and don't force the MQTT_TOPIC
- Restored the fps to the K10056SetResolvingBit message
- Lots more logging to help track down the recording issue
- Cleanup a bunch of Python warnings
- Bump MediaMTX to 1.12.3
- Bump Wyze app version to 3.5.5.8
- Don't force MediaMTX logging level to info
- Better tagging for Docker images
- Unified more the normal/hardware/multiarch docker build files
- Add devcontainer.json and tasks.json for VSCode

## What's Changed in v3.10.9

- Revert tutk_protocol change in `K10056SetResolvingBit`

## What's Changed in v3.10.8

- Removed forced leading "/" from RECORD_PATH
- Removed the IP restrictions from the MediaMTX "publisher" role
- Sync up with Elliot Kroo's [wyzecam library](https://github.com/kroo/wyzecam)
  - add HL_WCO2 camera support
  - K10020CheckCameraParams support
  - Fix `authentication_type`'s type
  - Add fps to the `K10056SetResolvingBit` message
  - Fix time setting to always advance one second (for lag) in `K10092SetCameraTime`
  - Send/recv time and blank (PST flag?) to `K11006GetCurCruisePoint`/`K11010GetCruisePoints`/`K11012SetCruisePoints`
- Changed the MediaMTX config builder to emit correct config for recording
- Cleanup the warnings in the app code and added `mtx_event` pipe receipt logging
- Updated Wyze iOS app version to 3.5.0.8 (for user agent)
- Use `SIGTERM` for more graceful shutdown
- More startup logging for the MTX configuration of `RECORD_PATH`
- Sync up all the ports listed in MediaMTX with the ports exposed in the docker-compose files

## What's Changed in v3.10.7

- Reverted defaulting of RECORD_PATH option specifying `{cam_name}` instead of `%path` (need to fix that another way)
- Changed the MediaMTX config builder to emit correct config for recording.
  
## What's Changed in v3.10.6

- ~Changed the documentation and defaults for the RECORD_PATH option to specify `{cam_name}` instead of `%path` to
  eliminate recording errors~ Reverted in v3.10.7
- Add exception handling to ffmpeg pruning logic to prevent snapshot prunes from killing each other
- Now gathers the list of parents that might be pruned and does that after purging the files
- Fixed python lint message in get_livestream_cmd

## What's Changed in v3.10.5

- Fix regression for snapshot pruning

## What's Changed in v3.10.4

- Catch exceptions when pruning snapshots so we don't stop grabbing them if something breaks a prune.
- Allow the ffmpeg error messages to reach the normal runtime
- Bump to [MediaMTX 1.12.2](https://github.com/bluenviron/mediamtx/releases/tag/v1.12.2) to [fix regression on RaspberryPIs](https://github.com/bluenviron/mediamtx/compare/v1.12.1...v1.12.2)

## What's Changed in v3.10.3

- Bump MediaMTX to 1.12.1

## What's Changed in v3.10.2

- Added code to protect against the aggressive syntax check in MediaMTX 1.12.0 which
  complains about the `recordPath` missing required elements even when recording is
  not enabled (it really shouldn't validate that setting unless one or more paths
  request recording...and didn't through 1.11.3).
  For reference, the pattern is computed from our `RECORD_PATH` and `RECORD_FILE_NAME`
  settings and the combination of them must contain the `strftime` format specifiers
  of *either* a `"%s"` or **all** of of "%Y", "%m", "%d", "%H", "%M", "%S" (case-sensitive).
  If the value is not compliant, to keep MediaMTX from erroring out, we append `"_%s"` whatever
  was specified and emit a warning.
- Changed the default `RECORD_PATH` to ~`"record/%path/%Y/%m/%d/"`~ *v3.10.7* `"%path/{cam_name}/%Y/%m/%d"`
- Changed the default `RECORD_FILE_NAME` to `"%Y-%m-%d-%H-%M-%S"`

## What's Changed in v3.10.1

- Add `TOTP_KEY` and `MQTT_DTOPIC` to *config.yml* schema to avoid logged warning noise
- Add `MQTT_DTOPIC` to *config.yml* options to ensure a usable default
- Add `video: true` to all the *config.yml* variants to ensure hardware encoding can
  use video card
- Upgrade to `python:3.13-slim-bookworm` for docker base image
- Cleaned up Dockerfile scripts for testing and multiarch
- Safer docker build by testing the tarballs downloaded for MediaMTX or FFMpeg

## What's Changed in v3.10.0

- Attempt upgrade of MediaMTX to 1.12.0 (again)
- Fixed schema of RECORD_LENGTH config option (it needs an `s` or `h` suffix, so must be string)
- Added RECORD_KEEP to the config.yml so it can be actually be configured in the add-on

## What's Changed in v3.0.7

- Better logging of exceptions and pass the MediaMTX messages through to main logs
- Correct building of permissions for MediaMTX
- Documented all the possible points in the docker-compose files.

## What's Changed in v3.0.6

- Revert MediaMTX to 1.11.3 because 1.12 doesn't work here.

## What's Changed in v3.0.5 ~DELETED~

- Fix MediaMTX to pass a user name [since 1.12.0 now requires one](https://github.com/bluenviron/mediamtx/compare/v1.11.3...v1.12.0#diff-b5c575fc54691bae05c5cc598fac91c97876b3d15687c359f970a8b832ab3ab6R23-R41)

## What's Changed in v3.0.4  ~DELETED~

- Chore: Bump [MediaMTX to 1.12.0](https://github.com/bluenviron/mediamtx/releases/tag/v1.12.0)

## What's Changed in v3.0.3

Rehoming this to ensure it lives on since PR merges have stalled in the original (and most excellent) @mrlt8 repo, I am surfacing a new
release with the PRs I know work. **Note** The badges on the GitHub repo may be broken and the donation links *still* go to @mrlt8 (as they should!)

- Chore: Bump Flask to 3.1.*
- Chore: Bump Pydantic to 2.11.*
- Chore: Bump Python-dotenv to 1.1.*
- Chore: Bump MediaMTX to 1.11.3
- FIX: Add host_network: true for use in Home Assistant by @jdeath to allow communications in Docker
- FIX: Hardware accelerated rotation by @giorgi1324
- Enhancement: Add more details to the cams.m3u8 endpoint by @IDisposable
- FIX: Fix mixed case when URI_MAC=true by @unlifelike
- Update: Update Homebridge-Camera-FFMpeg documentation link by @donavanbecker
- FIX: Add formatting of {cam_name} and {img} to webhooks.py by @traviswparker which was lost
- Chore: Adjust everything for move to my GitHub repo and Docker Hub account

[View previous changes](https://github.com/idisposable/docker-wyze-bridge/releases)

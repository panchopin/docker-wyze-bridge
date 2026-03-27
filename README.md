# Docker Wyze Bridge V4.0.2 (thatdaveguy fork)

[![GitHub release (latest by date)](https://img.shields.io/github/v/release/thatdaveguy1/docker-wyze-bridge?logo=github)](https://github.com/thatdaveguy1/docker-wyze-bridge/releases/latest)
[![GHCR Package](https://img.shields.io/badge/ghcr-package-blue?logo=github)](https://ghcr.io/thatdaveguy1/docker-wyze-bridge)
[![Home Assistant Add-on](https://img.shields.io/badge/home_assistant-add--on-blue.svg?logo=homeassistant&logoColor=white)](./docs/user_guide/install_ha.md)

### WebRTC/RTSP/RTMP/HLS Bridge for Wyze Cam

![Wyze Bridge UI](https://user-images.githubusercontent.com/67088095/224595527-05242f98-c4ab-4295-b9f5-07051ced1008.png)

Create a local WebRTC, RTSP, RTMP, or HLS/Low-Latency HLS stream for your Wyze cameras. This fork is tuned for the current Wyze lineup, with stronger defaults for modern cameras and a cleaner **Home Assistant** experience.

- No modifications, third-party, or special firmware required.
- Built to be easier to install, easier to understand, and easier to keep running.
- Streams direct from camera without additional bandwidth or subscriptions.
- Local high-performance WebRTC and RTSP backend.

## Why Choose This Fork

- Better defaults for modern Wyze cameras, especially V3, V3 Pro, and V4.
- A more beginner-friendly Home Assistant add-on with cleaner docs and safer defaults.
- The Home Assistant add-on now surfaces the standard `Wyze email`, `Wyze password`, `Key ID`, and `API key` fields by default.
- Sub-stream messaging now explains that support follows the internal capability map instead of implying every camera supports it.
- A more usable web UI with copy-ready stream URLs and clearer protocol availability.
- Practical reliability work around startup timing, session lifetime, and long-running bridge stability.

---

## 🚀 Quick Start

### 1. Prerequisites
- Your Wyze account email and password.
- **API Key and API ID:** Required as of April 2024. Get them from the [Wyze Support Article](https://support.wyze.com/hc/en-us/articles/16129834216731).

### 2. Choose your Platform

| Platform | Guide |
| :--- | :--- |
| **Home Assistant (Add-on)** | [HA Install Guide](./docs/user_guide/install_ha.md) |
| **Docker (CLI / Compose)** | [Docker Install Guide](./docs/user_guide/install_docker.md) |
| **Unraid** | [Template XML](./unraid/docker-wyze-bridge.xml) |

---

## 🆕 What's New in V4.0.2

- **Safer KVS/WHEP Startup:** The WHEP proxy now exposes downstream output tracks only after real upstream audio/video media is ready, which reduces early attach failures during camera startup.
- **Hardened Bridge Initialization:** If Wyze login succeeds but `get_user_info` fails or returns empty, the bridge now falls back to the configured Wyze email instead of crashing during startup.
- **Better HA Validation Workflow:** The Home Assistant prod/dev swap helper stays intentionally minimal while in-app diagnostics and live log checks remain the preferred way to validate bridge behavior.
- **Patch Release Scope:** `4.0.2` focuses on runtime stability and release hardening for the V4 fork line rather than introducing new camera-facing features.

### What V4.0 Introduced

- **WebRTC-Capable Cameras:** The KVS/WebRTC path became the default for WebRTC-capable cameras, including V3, V3 Pro, and V4.
- **Polished Web UI:** One-click copy buttons for stream URLs and improved protocol status reporting.
- **Home Assistant Optimized:** New `docker_wyze_bridge_v4` slug, ingress-aware base URLs, and conflict-free port mapping.
- **MediaMTX V1.16.3:** Upgraded backend for lower latency and better stability.
- **Stability Fixes:** Resolved several long-running session and process-cleanup bugs.

---

## 📷 Supported Cameras

![Wyze Cam V1](https://img.shields.io/badge/wyze_v1-yes-success.svg)
![Wyze Cam V2](https://img.shields.io/badge/wyze_v2-yes-success.svg)
![Wyze Cam V3](https://img.shields.io/badge/wyze_v3-yes-success.svg)
![Wyze Cam V3 Pro](https://img.shields.io/badge/wyze_v3_pro-yes-success.svg)
![Wyze Cam V4](https://img.shields.io/badge/wyze_v4-yes-success.svg)
![Wyze Cam Floodlight](https://img.shields.io/badge/wyze_floodlight-yes-success.svg)
![Wyze Cam Floodlight V2](https://img.shields.io/badge/wyze_floodlight_v2-yes-success.svg)
![Wyze Cam Pan](https://img.shields.io/badge/wyze_pan-yes-success.svg)
![Wyze Cam Pan V2](https://img.shields.io/badge/wyze_pan_v2-yes-success.svg)
![Wyze Cam Pan V3](https://img.shields.io/badge/wyze_pan_v3-yes-success.svg)
![Wyze Cam Pan Pro](https://img.shields.io/badge/wyze_pan_pro-yes-success.svg)
![Wyze Cam Outdoor](https://img.shields.io/badge/wyze_outdoor-yes-success.svg)
![Wyze Cam Outdoor V2](https://img.shields.io/badge/wyze_outdoor_v2-yes-success.svg)
![Wyze Cam Doorbell](https://img.shields.io/badge/wyze_doorbell-yes-success.svg)
![Wyze Cam Doorbell V2](https://img.shields.io/badge/wyze_doorbell_v2-yes-success.svg)

---

## 🛠 Documentation & Support

- 🆕 [V4.0.2 Release Notes](./docs/user_guide/release_notes_v4.md)
- 🆙 [Upgrade & Migration Guide](./docs/user_guide/upgrade.md)
- ❓ [Troubleshooting Guide](./docs/user_guide/troubleshooting.md)
- 📘 [Home Assistant Add-on Docs](./home_assistant/DOCS.md)
- 🧭 The repo also carries a maintainer runbook for reusing bridge-emitted MQTT motion inside Scrypted when Wyze software motion is unreliable: [Wyze Scrypted MQTT Runbook](./docs/runbooks/wyze-scrypted-mqtt-runbook.md).
- 🧰 The Home Assistant prod/dev bridge handoff helper is documented here: [HA Dev Swap Helper](./docs/runbooks/ha-dev-swap-helper.md).
- 🧯 On this HA box, Frigate is fed from Scrypted RTSP rebroadcast URLs rather than directly from Wyze Bridge; when those feeds became unstable on March 20, 2026, the live Frigate config was stabilized by setting `ffmpeg.hwaccel_args: ""` and `input_args: preset-rtsp-restream` on the Scrypted RTSP inputs.
- 🧪 A fully documented live Scrypted test also tried disabling `north-yard` audio inside the Scrypted RTSP device to see whether that would calm prebuffer sync issues. It changed the stream to video-only, but it did not resolve the `Unable to find sync frame in rtsp prebuffer` / Frigate instability and was rolled back.
- 🧪 On March 23, 2026, a live Scrypted snapshot test temporarily forced `South Driveway E1 CX` and `Reolink Doorbell` to use Snapshot-plugin prebuffer snapshots via a patched add-on backup restore. Scrypted restarted cleanly, but the post-restore logs did not show a durable reduction in snapshot failures before the system was rolled back to the original `c20d03f1` backup.
- 🧪 Repository-local Home Assistant staging is maintained through `.ha_live_addon/` as a separate `Dev Build` add-on before fixes are promoted into production sources.
- 🧰 On Home Assistant systems where local add-on store reload is blocked, the SSH staging helpers can reuse an already-indexed local add-on slot as the dev lane.
- 🧪 On March 26, 2026, the WHEP proxy source gained targeted instrumentation for normal websocket `1001 Going away` upstream closes so dog-run peer/media state can be logged at the moment of rotation. Production/runtime parity was later confirmed through the local dev add-on lane rather than the repository-backed production add-on.
- 🧪 The follow-up normal-close experiment now exits the websocket reader cleanly after a healthy `1001 Going away` rotation instead of continuing on a socket that was already closed; this is the next candidate behavior to validate in the Home Assistant dev lane.
- 🧪 In the March 26 dev-lane validation window, the next observed `1001 Going away` rotation for `dog-run` logged the healthy keep-alive path and did not reproduce the earlier immediate `127.0.0.1:8080` refusal / MediaMTX collapse in the first post-rotation watch window.
- 🧪 A later same-session spot check still showed fresh `dog_run` image responses in Frigate while direct HA-shell probes to local bridge internals (`127.0.0.1:8080`, `:59997`) failed, so the next investigation step is separating container/network-namespace visibility from any real listener/process regression.
- 🧰 The repo now includes `scripts/ha_bridge_diag.sh`, which queries a new in-app `/health/details` endpoint so future `whep_proxy` and MediaMTX probes run from inside the bridge namespace instead of guessing from the Home Assistant shell.
- 🧪 In a longer March 26 dev-lane soak, `dog-run` survived another observed `1001 Going away` rotation and stayed healthy well afterward; `scripts/ha_bridge_diag.sh --stream dog-run` continued to report `whep_proxy` `upstream_alive=true` and `can_reuse=true` with no new `dog_run` failures in Frigate.
- 🧪 The later MediaMTX diagnostics follow-up showed that `127.0.0.1:59997` was not a hidden namespace issue: the add-on passes `MTX_APIADDRESS=:59997`, but MediaMTX Control API stays disabled unless `MTX_API=true`, so the diagnostics helper now reports that state explicitly instead of treating it as a broken listener.
- 🧪 A later dev-lane regression turned out to be a host-network port-race, not a new MediaMTX config bug: repeated `Process exited with 1` crashes traced to `listen udp :58000: bind: address already in use` during rapid prod/dev swap timing. `scripts/ha_dev_build.sh` is now intentionally kept as a minimal swap helper: wait for shared ports to clear, swap one bridge at a time, and verify `/health` before continuing.
- 🧪 The next March 26 `dog-run` repro confirmed the earlier startup symptom in the dev lane too: MediaMTX hit `deadline exceeded while waiting tracks`, Frigate immediately lost `dog_run`, and the proxy still exposed reusable local tracks before real upstream media was ready. The WHEP proxy now gates output tracks on `video_ready` / `audio_ready` instead of merely track allocation, but the latest redeploy also exposed a separate dev-lane auth startup failure (`get_user_info` returned `None`, then `wyze_bridge.py` crashed while reading `.email`), so live validation of the gating fix is currently blocked until that auth/init failure is cleared.
- 🧪 The follow-up auth fix is now in place: when `get_user_info` fails or returns empty, the bridge builds a fallback local user profile from the configured Wyze email instead of crashing during init. In the next live dev-lane validation, startup completed cleanly, `/health/details?stream=dog-run` reported `video_ready=true`, `audio_ready=true`, and `upstream_alive=true`, and the earlier `deadline exceeded while waiting tracks` window did not reappear for `dog-run` in that startup pass.

---

## 💖 Credits & Attribution

This fork is built on the excellent work of the original authors and contributors.

- **idisposable/docker-wyze-bridge**: Base fork and release line.
- **akeslo/docker-wyze-bridge**: KVS/WebRTC signaling and architectural direction.
- **kroo/wyzecam**: Fundamental Wyze API and TUTK implementation.
- **aler9/mediamtx**: High-performance streaming backend.

Please consider starring this project if you find it useful!

> [!IMPORTANT]
> This project is not affiliated with Wyze Labs, Inc. Use at your own risk.

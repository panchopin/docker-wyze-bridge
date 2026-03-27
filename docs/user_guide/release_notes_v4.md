# Release Notes V4.0.2

The **Docker Wyze Bridge V4.0.2** is a focused patch release for the V4 fork line. It keeps the broader platform direction from `4.0.0` and the Home Assistant cleanup from `4.0.1`, then adds startup hardening around the real bridge/runtime issues found during Home Assistant live validation.

## Why this Fork Exists?

The original upstream bridge (`idisposable/docker-wyze-bridge` and `mrlt8/docker-wyze-bridge`) provided the foundation for local Wyze streaming. However, as Wyze introduced newer cameras like the **Wyze Cam V4**, the bridge needed a more robust and scalable backend for WebRTC and KVS (Kinesis Video Streams).

This fork aims to:
- Provide first-class support for **Wyze Cam V4** and other newer models.
- Improve the beginner experience in Home Assistant.
- Stabilize the bridge for 24/7 streaming reliability.
- Support modern WebRTC-backed RTSP and HLS delivery.

## What's New in V4.0.2

### Startup stability hardening
- **Ready-only downstream tracks:** The WHEP proxy no longer treats preallocated local RTP tracks as usable output. Downstream clients only see tracks after upstream audio/video media is actually ready.
- **Better startup behavior:** This reduces the chance that on-demand WHEP and RTSP consumers attach during the earliest startup gap and trigger failures like `deadline exceeded while waiting tracks`.

### Bridge init hardening
- **Fallback user profile:** If Wyze authentication succeeds but `get_user_info` fails or returns empty, the bridge now derives the minimum local account context from the configured Wyze email instead of crashing during startup.
- **Safer local auth setup:** Home Assistant startup can continue far enough to initialize streams and diagnostics even when the richer Wyze account profile is temporarily unavailable.

### Home Assistant validation workflow
- **Minimal swap helper:** The prod/dev handoff helper stays intentionally small and reversible instead of taking on stream-specific diagnostics logic.
- **In-app diagnostics first:** The release workflow now leans on `/health/details` and focused live logs for runtime validation inside the add-on namespace.

### Scope and notes for this patch
- **Patch-level release:** `4.0.2` is a runtime reliability release, not a feature expansion release.
- **Validated path:** The auth/init crash was fixed and the follow-up Home Assistant dev-lane validation completed cleanly with `dog-run` reaching `video_ready=true`, `audio_ready=true`, and `upstream_alive=true` during the successful startup pass.

## What V4.0 and V4.0.1 already introduced

### Wyze Cam V4 Support
- **New KVS/WebRTC Backend:** In the current code, the KVS/WebRTC path is the default for all WebRTC-capable cameras, not just V4. That includes V3, V3 Pro, V4, Pan, Pan V2, Pan V3, Floodlight V2, Floodlight Pro, OG, and other models that are not in the `NO_WEBRTC` list.
- **Improved Authentication:** Added support for modern Wyze API and signaling protocols.

### Home Assistant Integration
- **Polished Add-on:** The Home Assistant add-on has been redesigned with a clean configuration UI and better logging.
- **Ingress Support:** The Web UI is now fully integrated into Home Assistant with automatic authentication.
- **Port Conflict Resolution:** Default ports for Home Assistant users are now `58554` (RTSP), `58888` (HLS), and `58889` (WebRTC) to avoid common conflicts with other add-ons.

### Web UI and Usability
- **One-Click Copy Buttons:** Every stream in the Web UI now has a copy icon for easy URL retrieval.
- **Smart Protocol Availability:** The bridge now correctly identifies which protocols (RTSP, RTMP, HLS, WebRTC) are available for each camera.
- **Improved Status Reporting:** Clearer logs and status indicators in the Web UI for better troubleshooting.

### Stability and Performance
- **MediaMTX V1.16.3:** Upgraded to the latest MediaMTX release for better WebRTC track gathering and lower latency.
- **Process and Thread Safety:** Fixed several child-process and threading bugs to reduce CPU and memory leaks during long-running sessions.
- **Session Lifetime Fixes:** Improved handling of Wyze session contexts to ensure streams stay open during bridge reads.

## What's Inherited?
The V4 fork line builds on the excellent work of:
- **`idisposable/docker-wyze-bridge`**: For the core bridge architecture and Home Assistant packaging.
- **`akeslo/docker-wyze-bridge`**: For the initial KVS/WebRTC signaling and architectural direction.
- **`kroo/wyzecam`**: For the fundamental Wyze API and TUTK implementation.
- **`aler9/mediamtx`**: For the high-performance streaming server.

## Current Limits and Known Issues
- **H264 PPS Warnings:** `ffprobe` may still show transient H264 PPS warnings on the first cold attach. The stream will still work after a few seconds.
- **Wi-Fi Stability:** Newer KVS-backed streams are sensitive to Wi-Fi stability. If your camera is far from your router, you may experience connection timeouts.
- **Legacy Camera Support:** Some older Wyze models (e.g., V1, some doorbells) may still use the original TUTK path.

## Attribution and Provenance
Detailed file-by-file attribution and provenance records are maintained internally. For questions about specific changes or upstream contributions, please open an issue.

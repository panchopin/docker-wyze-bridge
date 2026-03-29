# Upgrade Guide

This guide covers upgrading to the `4.2` release line of Docker Wyze Bridge from older upstream builds or earlier releases in this fork.

## What Changes in 4.2

- The visible product name is now `Docker Wyze Bridge`.
- The Home Assistant add-on now bundles a native `go2rtc` sidecar and exposes RTSP on `:19554`.
- The shared Web UI now exposes granular per-camera `HD` and `SD` feed selection with separate bitrate targets.
- Public documentation now includes model-specific stream ceilings and substream limits for `V3`, `V3 Pro`, `V4`, and `Wyze Bulb Cam`.

## Migration Steps

1. Back up your Home Assistant add-on configuration.
2. Stop any older bridge add-on that still uses the same RTSP or Web UI ports.
3. Install or update to `Docker Wyze Bridge`.
4. Re-enter or paste your `Wyze Email`, `Wyze Password`, `Key ID`, and `API Key` if needed.
5. Update any RTSP consumers that should use the native Home Assistant sidecar to point at `:19554`.

## Port Notes

Standard Home Assistant ports remain:

- `5000` Web UI
- `58554` bridge RTSP
- `58888` HLS
- `58889` WebRTC / WHEP

New supported native RTSP surface:

- `19554` native `go2rtc` RTSP

The internal sidecar API on `:11984` is not a stable public interface.

## Known Upgrade Caveats

- A camera can gain a native `go2rtc` RTSP path without gaining a better resolution ceiling.
- `QUALITY` values still do not override Wyze-side resolution decisions.
- A `-sub` alias does not guarantee a distinct lower-resolution helper feed.

See [Camera Support](./camera_support.md) for model-specific notes.

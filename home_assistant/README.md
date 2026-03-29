# Docker Wyze Bridge

This Home Assistant add-on provides local WebRTC, RTSP, RTMP, and HLS access for Wyze cameras. The `4.2` release line keeps the established bridge path, bundles a native `go2rtc` sidecar for Home Assistant, and documents the model-specific limits now known for newer Wyze cameras.

## Installation

1. Add the repository to Home Assistant: `https://github.com/thatdaveguy1/docker-wyze-bridge`
2. Install the `Docker Wyze Bridge` add-on.
3. Fill in the visible login fields: `Wyze Email`, `Wyze Password`, `Key ID`, and `API Key`.
4. Start the add-on and open the Web UI.

## Home Assistant Features

- Standard bridge ports remain available for Web UI, RTSP, HLS, and WHEP.
- The add-on now bundles a native `go2rtc` sidecar and exposes supported RTSP output on `:19554`.
- The internal sidecar API on `:11984` is not part of the stable public interface.

## Camera Limits

Public `4.2` behavior is documented by model, including current resolution ceilings and whether a meaningful main/sub split is available.

- Wyze Cam V3: bridge path validated up to `1920x1080`, with firmware-gated substream support.
- Wyze Cam V3 Pro: bridge main validated up to `2560x1440`; `4.2` does not promise a fixed substream ceiling on every install.
- Wyze Cam V4: Home Assistant native `go2rtc` is the best-documented RTSP path in `4.2`; validated native output reached `2560x1440` main and `640x360` substream.
- Wyze Bulb Cam: supported, but current public `4.2` validation keeps both main and `-sd` feeds at `640x360`.

See [Camera Support](../docs/user_guide/camera_support.md) for the full matrix.

## Documentation

- [Main README](../README.md)
- [Home Assistant Docs](./DOCS.md)
- [Install Guide](../docs/user_guide/install_ha.md)
- [Upgrade Guide](../docs/user_guide/upgrade.md)
- [Troubleshooting](../docs/user_guide/troubleshooting.md)

## Attribution

This fork builds on work from `idisposable/docker-wyze-bridge`, `akeslo/docker-wyze-bridge`, `kroo/wyzecam`, `aler9/mediamtx`, and `AlexxIT/go2rtc`.

The bundled Home Assistant native sidecar uses `go2rtc` from `AlexxIT/go2rtc` under the MIT license. See [THIRD_PARTY_NOTICES.md](../THIRD_PARTY_NOTICES.md).

> [!IMPORTANT]
> This project is not affiliated with Wyze Labs, Inc. Use at your own risk.

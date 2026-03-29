# Home Assistant Install Guide

`Docker Wyze Bridge` is available as a Home Assistant add-on.

## Prerequisites

- Home Assistant with Supervisor
- Wyze developer `API ID` and `API Key`
- Wyze account email and password

## Add the Repository

1. In Home Assistant, open `Settings` > `Add-ons`.
2. Open the Add-on Store.
3. Add this repository:

```text
https://github.com/thatdaveguy1/docker-wyze-bridge
```

## Install the Add-on

1. Install `Docker Wyze Bridge` from the Add-on Store.
2. Open the `Configuration` tab.
3. Fill in `Wyze Email`, `Wyze Password`, `Key ID`, and `API Key`.
4. Start the add-on.

## Default Ports

- `5000`: Web UI
- `58554`: standard bridge RTSP
- `58888`: HLS
- `58889`: WebRTC / WHEP
- `59997`: MediaMTX API
- `19554`: native Home Assistant `go2rtc` RTSP

The sidecar API on `:11984` exists internally but is not part of the stable public interface.

## Camera Notes

The add-on supports the broader Wyze lineup, but the `4.2` release now publishes model-specific limits more explicitly:

- `V3`: validated V3-class bridge paths have reached `1920x1080`, with firmware-gated substream support.
- `V3 Pro`: validated main stream reached `2560x1440`.
- `V4`: Home Assistant native `go2rtc` is the best documented RTSP path in `4.2`, with validated native output at `2560x1440` main and `640x360` substream.
- `Wyze Bulb Cam`: supported, but current public validation keeps both main and `-sd` at `640x360`.

See [Camera Support](./camera_support.md) for the full matrix.

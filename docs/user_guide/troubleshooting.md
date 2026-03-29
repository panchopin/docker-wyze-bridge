# Troubleshooting Guide

This guide covers common issues for Docker Wyze Bridge.

## Login and API Issues

### Invalid API credentials

- Confirm the `API ID` and `API Key` were generated from Wyze developer access.
- Recheck for whitespace before or after the values.
- Confirm the Wyze account email and password match the same account.

### No cameras found

- Confirm your cameras are attached to the same Wyze account.
- Check the logs for Wyze API errors.
- Verify the account actually contains supported Wyze cameras.

## Stream Issues

### RTSP stream does not load

- Check the add-on logs for startup or connection failures.
- Confirm you are using the intended RTSP surface:
  - `:58554` for the standard bridge path
  - `:19554` for the Home Assistant native sidecar path
- Verify the camera is online in the Wyze app.

### Camera only shows lower resolution than expected

- `QUALITY` values are requests, not guarantees.
- Newer Wyze cameras can still publish lower-resolution KVS/WebRTC output than their advertised sensor resolution.
- A native Home Assistant sidecar path may improve RTSP behavior for some cameras, but it does not guarantee a higher ceiling for every model.

### Main and substream look identical

- A `-sub` alias can exist without exposing a truly different stream profile.
- This is a known `4.2` limitation for some newer cameras, especially when Wyze firmware only exposes one effective KVS/WebRTC profile.

## Model-Specific Notes

### Wyze Cam V3

- Bridge substream support depends on firmware `4.36.10+`.
- Current public V3-class validation reached `1920x1080`, but higher output is not guaranteed.

### Wyze Cam V3 Pro

- Public `4.2` validation reached `2560x1440` main-stream output.
- `4.2` does not promise a fixed public substream ceiling on every host.

### Wyze Cam V4

- Standard bridge RTSP can still remain `640x360`.
- The best documented RTSP path in `4.2` is the Home Assistant native sidecar on `:19554`.
- TUTK fallback is not documented as a reliable quality-rescue path.

### Wyze Bulb Cam

- Supported, but current public `4.2` validation keeps both main and `-sd` feeds at `640x360`.
- If you need a guaranteed higher RTSP ceiling, `4.2` does not currently provide one for this model.

## Debugging

If you need deeper logs:

- Set `LOG_LEVEL=DEBUG`
- Set `FFMPEG_LOGLEVEL=verbose`

When filing a GitHub issue, include:

- camera model and firmware version
- redacted bridge configuration
- the exact RTSP surface used (`:58554` or `:19554`)
- a short log excerpt around the failure

# Troubleshooting Guide

This guide covers common issues and questions for the **Docker Wyze Bridge V4.0.2**.

## Login and API Issues

### "Invalid API Key ID or API Key"
- **Problem:** The bridge fails to log in with an API key error.
- **Solution:** 
  1.  Ensure you have followed the [Wyze Support Article](https://support.wyze.com/hc/en-us/articles/16129834216731) to generate your developer keys.
  2.  Double-check for extra spaces before or after the API ID and API Key.
  3.  Verify that your Wyze Email and Password are correct.

### "No Cameras Found"
- **Problem:** The bridge logs in successfully but doesn't list any cameras.
- **Solution:** 
  1.  Ensure your cameras are connected to the same Wyze account you used to log in.
  2.  Check the logs for any `Wyze API Pull Error`.
  3.  Verify your account has at least one supported Wyze camera.

## Stream and Connection Issues

### "RTSP Stream Not Loading"
- **Problem:** The RTSP stream fails to load in VLC or other players.
- **Solution:** 
  1.  Check the logs for `Stream Timeout` or `Connection Failed`.
  2.  If you are running in Docker, ensure you have mapped the correct RTSP port (`8554` or `58554` in HA).
  3.  Verify that your camera is online in the Wyze app.
  4.  Try switching to the **WebRTC (WHEP)** or **HLS** stream in the Web UI to see if it works.

### "WebRTC (WHEP) Lag or Latency"
- **Problem:** The WebRTC stream has significant delay or stuttering.
- **Solution:** 
  1.  Check your camera's Wi-Fi signal strength in the Wyze app.
  2.  Ensure you have enabled `WB_IP` or `network_mode: host` in your configuration.
  3.  Try decreasing the `QUALITY` setting for that camera in the `CAM_OPTIONS`.

### "V4 or V3 Camera Connection Issues"
- **Problem:** A Wyze Cam V4, V3, or V3 Pro fails to connect or has frequent disconnects.
- **Solution:** 
  1.  These cameras default to the KVS/WebRTC path in the current codebase.
  2.  Check for `deadline exceeded while waiting tracks` in the logs. If this appears, your camera's Wi-Fi may be unstable or too far from the bridge.

## Web UI and Authentication

### "401 Unauthorized"
- **Problem:** Accessing the Web UI or a stream results in a 401 error.
- **Solution:** 
  1.  If `WB_AUTH` is enabled, ensure you are using the correct username and password.
  2.  The default username is `wb` (or `admin` if configured), and the password is your unique `WB_PASSWORD` (or API key by default).
  3.  If you are using Home Assistant Ingress, auth is handled automatically, but relative paths may fail if accessed via the direct URL.

### "Copy Buttons Not Working"
- **Problem:** Clicking the copy icon in the Web UI doesn't copy the URL to the clipboard.
- **Solution:** 
  1.  Clipboard access requires a secure connection (HTTPS) in most browsers.
  2.  If you are using plain HTTP, the bridge will fallback to a manual prompt where you can copy the URL manually.

## Logging and Debugging

If you are still having issues, please enable debug logging:
- Set `LOG_LEVEL` to `DEBUG`.
- Set `FFMPEG_LOGLEVEL` to `verbose`.
- Check the logs for specific error codes or stack traces.

When reporting an issue on GitHub, please include:
- Your camera model and firmware version.
- Your bridge configuration (redact secrets!).
- A snippet of the logs during the failure.

# Docker Wyze Bridge V4.0.2 (thatdaveguy fork)

This Home Assistant add-on provides a local WebRTC, RTSP, RTMP, or HLS/Low-Latency HLS stream for your Wyze cameras. This fork is tuned for modern Wyze cameras and a smoother Home Assistant setup experience.

## 🚀 Installation

1.  Add the repository to Home Assistant: `https://github.com/thatdaveguy1/docker-wyze-bridge`
2.  Install the **Docker Wyze Bridge (V4.0.2)** add-on.
3.  Fill in the default visible login fields: **Wyze Email**, **Wyze Password**, **Key ID**, and **API Key**.
4.  **API Key and API ID:** Required as of April 2024. Get them from the [Wyze Support Article](https://support.wyze.com/hc/en-us/articles/16129834216731).
5.  Click **Start**.

## 🆕 What's New in V4.0.2

- **Safer startup:** The WHEP proxy now waits for real upstream media readiness before exposing downstream output tracks.
- **Crash-resistant init:** If Wyze account login works but profile lookup fails, the bridge now falls back to the configured email instead of aborting startup.
- **Home Assistant ready:** The V4 add-on keeps the optimized slug, ingress behavior, and conflict-aware ports while tightening runtime stability.
- **Focused patch:** This release is about reliability and release hardening, not a major feature reset.

## Why Use This Add-on

- Better defaults for current Wyze cameras, especially V3, V3 Pro, and V4.
- Cleaner install and setup flow for Home Assistant users.
- Easier stream copying and protocol visibility from the web UI.
- Reliability work aimed at real long-running use, not just first boot.

---

## 🛠 Documentation & Support

- 📖 [User Guide](https://github.com/thatdaveguy1/docker-wyze-bridge/blob/main/README.md)
- ❓ [Troubleshooting](https://github.com/thatdaveguy1/docker-wyze-bridge/blob/main/docs/user_guide/troubleshooting.md)
- 🆙 [Upgrade Guide](https://github.com/thatdaveguy1/docker-wyze-bridge/blob/main/docs/user_guide/upgrade.md)

---

## 💖 Credits & Attribution

This fork is built on the excellent work of the original authors and contributors:
- `idisposable/docker-wyze-bridge`
- `akeslo/docker-wyze-bridge`
- `kroo/wyzecam`
- `aler9/mediamtx`

> [!IMPORTANT]
> This project is not affiliated with Wyze Labs, Inc. Use at your own risk.

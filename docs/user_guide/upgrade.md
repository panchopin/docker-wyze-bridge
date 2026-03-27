# Upgrade and Migration Guide

This guide covers upgrading to **Docker Wyze Bridge V4.0.2** from earlier versions or from other forks.

## Upgrading from Upstream (idisposable/docker-wyze-bridge)

The V4.0.2 release keeps the V4 platform work intact while adding startup hardening for the Home Assistant bridge/runtime path.

### What has Changed?
- **New Home Assistant Slug:** The add-on now uses `docker_wyze_bridge_v4`. This allows it to install alongside the original upstream add-on if needed.
- **KVS/WebRTC Backend:** Support for Wyze Cam V4 and improved latency for V3/V3 Pro cameras.
- **Optimized Ports:** Defaults have changed for Home Assistant users (e.g., `58554` for RTSP) to avoid common port conflicts.
- **Polished Web UI:** New one-click copy buttons for stream URLs and improved status reporting.

### Migration Steps
1.  **Backup your configuration:** If you are using the Home Assistant add-on, copy your current Wyze credentials and `CAM_OPTIONS` from the configuration tab.
2.  **Stop the old add-on:** If you were using the upstream version, stop it before installing the V4.0.2 release to avoid port conflicts.
3.  **Add the new repository:** Follow the [Home Assistant Install Guide](./install_ha.md) to add the `thatdaveguy1/docker-wyze-bridge` repository.
4.  **Install V4.0.2:** Install the new **Docker Wyze Bridge (V4.0.2)** add-on and paste your saved configuration into the configuration tab.
5.  **Update your stream links:** If you have hardcoded RTSP or HLS links in your dashboards or Frigate, update them to use the new ports (`58554`, `58888`, `58889`).

## Troubleshooting Upgrades

### "Port already in use"
- **Problem:** The V4.0.2 add-on fails to start with a port conflict error.
- **Solution:** 
  1.  Ensure you have stopped any other versions of the bridge or other services using ports `8554`, `8888`, `8889`, or `5000`.
  2.  If you are in Home Assistant, check the **Configuration** tab and change the port mapping to an unused port block.

### "Cameras not connecting after upgrade"
- **Problem:** After upgrading, some cameras stay offline or fail to connect.
- **Solution:** 
  1.  Check the logs for `Wyze API Pull Error`. You may need to refresh your API credentials or clear the bridge's local cache.
  2.  Restart the bridge to clear any stale session data.

# Home Assistant Install Guide

The **Docker Wyze Bridge V4.0.2** is available as a Home Assistant Add-on. This is the easiest way to integrate your Wyze cameras into Home Assistant.

## Prerequisites

- Home Assistant installed with **Supervisor** (Home Assistant OS or Supervised).
- **API Key and API ID:** Required as of April 2024. Get them from the [Wyze Support Article](https://support.wyze.com/hc/en-us/articles/16129834216731).

## Step 1: Add the Repository

1.  In Home Assistant, go to **Settings** > **Add-ons**.
2.  Click the **Add-on Store** button in the bottom-right corner.
3.  Click the three-dot menu in the top-right corner and select **Repositories**.
4.  Paste the following URL into the text box:
    ```
    https://github.com/thatdaveguy1/docker-wyze-bridge
    ```
5.  Click **Add**, then click **Close**.

## Step 2: Install the Add-on

1.  The **Docker Wyze Bridge (V4.0.2)** should now be visible in the Add-on Store.
    *Note: If you don't see it, try refreshing the page or checking the store for a "New Repositories" section.*
2.  Select the add-on and click **Install**.
3.  Wait for the installation to complete (this may take a few minutes).

## Step 3: Configure the Add-on

1.  Go to the **Configuration** tab of the add-on.
2.  Fill in the default visible login fields: **Wyze Email**, **Wyze Password**, **Key ID**, and **API Key**.
3.  **Optional:** Set a custom `WB_USERNAME` and `WB_PASSWORD` for the Web UI and stream authentication (if `WB_AUTH` is enabled).
4.  Click **Save**.

## Step 4: Start the Add-on

1.  Go to the **Info** tab.
2.  Click **Start**.
3.  Check the **Log** tab to ensure the bridge connects to your Wyze account and finds your cameras.
4.  Enable **Show in sidebar** if you want easy access to the Web UI.

## Web UI and Ingress

The bridge includes a Web UI that can be accessed directly from the Home Assistant sidebar or by clicking **Open Web UI** on the add-on page. 

The Web UI allows you to:
- View live previews of your cameras.
- Get one-click copyable URLs for RTSP, WebRTC (WHEP), and HLS streams.
- See camera status and connection information.

## Ports and External Access

By default, the add-on uses the following ports for local network access:
- `58554`: RTSP (RTSP/WebRTC-backed)
- `58888`: HLS
- `58889`: WebRTC / WHEP
- `59997`: MediaMTX API

Advanced users can override MediaMTX port behavior through the add-on configuration, but most users should leave the defaults in place.

## Supported Cameras

The V4.0.2 release includes specific fixes and improvements for:
- **Wyze Cam V4:** Uses the default KVS/WebRTC path and is a major focus of this fork.
- **Wyze Cam V3 and V3 Pro:** Also use the default KVS/WebRTC path for lower latency and better stability.
- All other Wyze cameras are supported via the standard bridge path.

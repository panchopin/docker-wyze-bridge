#!/usr/bin/env python3

import importlib
import pathlib
import sys
import types
import unittest
from unittest.mock import patch

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "app"))

sys.modules.setdefault("xxtea", types.ModuleType("xxtea"))

fake_wyzecam_iotc = types.ModuleType("wyzecam.iotc")
fake_wyzecam_iotc.WyzeIOTC = object
fake_wyzecam_iotc.WyzeIOTCSession = object
sys.modules.setdefault("wyzecam.iotc", fake_wyzecam_iotc)


class FakeApi:
    def __init__(self):
        self.auth = True
        self.total_cams = 1

    def get_kvs_signal(self, cam_name):
        if cam_name != "deck":
            return {"result": "error"}
        return {
            "result": "ok",
            "cam": "deck",
            "signalingUrl": "wss://example.invalid/signaling",
            "clientId": "deck-client",
            "iceServers": [],
        }


class FakeStreams:
    total = 1
    active = 1

    def get_all_cam_info(self):
        return {
            "deck": {
                "enabled": True,
                "connected": False,
                "camera_info": None,
                "nickname": "Deck",
                "name_uri": "deck",
                "on_demand": False,
                "substream": False,
                "audio": True,
                "record": False,
                "webrtc": True,
                "rtsp_fw_enabled": False,
                "boa_url": None,
                "img_url": "img/deck.jpg",
                "snapshot_url": "snapshot/deck.jpg",
                "thumbnail_url": "thumb/deck.jpg",
                "preview_url": "snapshot/deck.jpg",
                "preview_refresh_mode": "snapshot",
                "hls_url": "http://homeassistant.local:58888/deck/",
                "webrtc_url": "http://homeassistant.local:58889/deck/",
                "rtsp_url": "rtsp://homeassistant.local:58554/deck",
                "rtmp_url": "rtmp://homeassistant.local:51935/deck",
                "img_time": 0,
                "is_battery": False,
            }
        }

    def get_sse_status(self):
        return {"deck": {"motion": False, "status": "stopped"}}


class FakeBridge:
    def __init__(self):
        self.api = FakeApi()
        self.streams = FakeStreams()

    def start(self):
        return None


fake_wyze_bridge = types.ModuleType("wyze_bridge")
fake_wyze_bridge.WyzeBridge = FakeBridge
sys.modules["wyze_bridge"] = fake_wyze_bridge

import frontend


class TestFrontendStaticAssets(unittest.TestCase):
    def create_client(self):
        sys.modules["wyze_bridge"] = fake_wyze_bridge
        importlib.reload(frontend)
        app = frontend.create_app()
        app.testing = True
        return app.test_client()

    def test_ingress_page_uses_ingress_prefixed_static_asset_urls(self):
        client = self.create_client()

        with patch.object(
            frontend.web_ui.auth, "login_required", side_effect=lambda fn: fn
        ):
            response = client.get(
                "/?video=1&webrtc=1",
                headers={"X-Ingress-Path": "/api/hassio_ingress/test-token"},
            )

        html = response.get_data(as_text=True)

        self.assertEqual(response.status_code, 200)
        self.assertIn(
            'href="/api/hassio_ingress/test-token/static/bulma.css"',
            html,
        )
        self.assertIn(
            'href="/api/hassio_ingress/test-token/static/site.css"',
            html,
        )
        self.assertIn(
            'src="/api/hassio_ingress/test-token/static/site.js"',
            html,
        )

    def test_webrtc_page_uses_ingress_prefixed_script_url(self):
        client = self.create_client()

        with patch.object(
            frontend.web_ui.auth, "login_required", side_effect=lambda fn: fn
        ):
            response = client.get(
                "/webrtc/deck",
                headers={"X-Ingress-Path": "/api/hassio_ingress/test-token"},
            )

        html = response.get_data(as_text=True)

        self.assertEqual(response.status_code, 200)
        self.assertIn(
            'src="/api/hassio_ingress/test-token/static/webrtc.js"',
            html,
        )

    def test_site_js_hides_hd_controls_in_sd_only_mode(self):
        site_js = pathlib.Path(__file__).resolve().parent.parent / "app" / "static" / "site.js"
        script = site_js.read_text(encoding="utf-8")

        self.assertIn("config.sd_only", script)
        self.assertIn('feed === "hd"', script)
        self.assertIn("button.hidden = hideFeed", script)
        self.assertIn('input.closest(".control")', script)

    def test_static_site_css_is_served(self):
        client = self.create_client()

        response = client.get("/static/site.css")

        self.assertEqual(response.status_code, 200)
        self.assertIn("background-color", response.get_data(as_text=True))

    def test_webrtc_script_refreshes_signal_from_root_path(self):
        script = (pathlib.Path(__file__).resolve().parent.parent / "app" / "static" / "webrtc.js").read_text()
        self.assertIn("new URL(`/signaling/${this.signalJson.cam}?${this.whep ? 'webrtc' : 'kvs'}`, window.location.href)", script)
        self.assertNotIn("new URL(`signaling/${this.signalJson.cam}?${this.whep ? 'webrtc' : 'kvs'}`, window.location.href)", script)


if __name__ == "__main__":
    unittest.main()

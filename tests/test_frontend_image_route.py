#!/usr/bin/env python3

import importlib
import pathlib
import sys
import tempfile
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
    auth = True
    total_cams = 1


class FakeStreams:
    def refresh_preview(self, _cam_name):
        return {"ok": False, "source": "test"}

    def get_snapshot(self, _cam_name):
        return {"ok": False, "source": "test"}


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


class TestFrontendImageRoute(unittest.TestCase):
    def create_client(self):
        sys.modules["wyze_bridge"] = fake_wyze_bridge
        importlib.reload(frontend)
        app = frontend.create_app()
        app.testing = True
        return app.test_client()

    def test_img_route_rejects_zero_byte_preview_file(self):
        client = self.create_client()

        with tempfile.TemporaryDirectory() as temp_dir:
            image_path = pathlib.Path(temp_dir) / "south-yard-sub.jpg"
            image_path.write_bytes(b"")

            with (
                patch.object(frontend.config, "IMG_PATH", temp_dir + "/"),
                patch.object(frontend.config, "SNAPSHOT_TYPE", "api"),
                patch.object(frontend.web_ui.auth, "login_required", side_effect=lambda fn: fn),
            ):
                response = client.get("/img/south-yard-sub.jpg")

            self.assertEqual(response.status_code, 307)
            self.assertIn("/static/notavailable.svg", response.location)
            self.assertFalse(image_path.exists())

    def test_img_route_rejects_html_preview_file_with_jpg_extension(self):
        client = self.create_client()

        with tempfile.TemporaryDirectory() as temp_dir:
            image_path = pathlib.Path(temp_dir) / "garage.jpg"
            image_path.write_text("<!doctype html><html>redirect</html>", encoding="utf-8")

            with (
                patch.object(frontend.config, "IMG_PATH", temp_dir + "/"),
                patch.object(frontend.config, "SNAPSHOT_TYPE", "api"),
                patch.object(frontend.web_ui.auth, "login_required", side_effect=lambda fn: fn),
            ):
                response = client.get("/img/garage.jpg")

            self.assertEqual(response.status_code, 307)
            self.assertIn("/static/notavailable.svg", response.location)
            self.assertFalse(image_path.exists())

    def test_snapshot_hash_registry_endpoint_returns_hashes(self):
        client = self.create_client()

        with tempfile.TemporaryDirectory() as temp_dir:
            registry_path = pathlib.Path(temp_dir) / ".snapshot_hashes.json"
            registry_path.write_text(
                '{"garage":{"sha256":"abc123","bytes":42,"source":"test","recorded_at":1}}\n',
                encoding="utf-8",
            )

            with (
                patch.object(frontend.config, "IMG_PATH", temp_dir + "/"),
                patch.object(frontend.web_ui.auth, "login_required", side_effect=lambda fn: fn),
            ):
                response = client.get("/api/snapshot-hashes")

            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.get_json()["registry"]["garage"]["sha256"], "abc123")


if __name__ == "__main__":
    unittest.main()

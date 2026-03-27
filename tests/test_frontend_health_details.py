#!/usr/bin/env python3

import importlib
import pathlib
import sys
import types
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "app"))


class FakeApi:
    def __init__(self):
        self.auth = True
        self.total_cams = 1


class FakeStreams:
    pass


class FakeBridge:
    def __init__(self):
        self.api = FakeApi()
        self.streams = FakeStreams()

    def start(self):
        return None

    def health(self):
        return {"mtx_alive": True, "wyze_authed": True, "active_streams": 5}

    def health_details(self, stream_name=None):
        return {
            "mtx_alive": True,
            "wyze_authed": True,
            "active_streams": 5,
            "stream": stream_name,
            "whep_proxy": {"reachable": True},
            "mediamtx": {"reachable": True},
        }


fake_wyze_bridge = types.ModuleType("wyze_bridge")
fake_wyze_bridge.WyzeBridge = FakeBridge
sys.modules["wyze_bridge"] = fake_wyze_bridge

import frontend


class TestFrontendHealthDetails(unittest.TestCase):
    def create_client(self):
        sys.modules["wyze_bridge"] = fake_wyze_bridge
        importlib.reload(frontend)
        app = frontend.create_app()
        app.testing = True
        return app.test_client()

    def test_health_details_returns_stream_specific_diagnostics(self):
        client = self.create_client()

        response = client.get("/health/details?stream=dog-run")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["stream"], "dog-run")
        self.assertTrue(response.get_json()["whep_proxy"]["reachable"])
        self.assertTrue(response.get_json()["mediamtx"]["reachable"])


if __name__ == "__main__":
    unittest.main()

#!/usr/bin/env python3

import pathlib
import sys
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "app"))

from wyzebridge.bridge_diagnostics import mediamtx_probe, whep_proxy_probe


class TestBridgeDiagnostics(unittest.TestCase):
    @patch.dict(
        "os.environ", {"MTX_API": "true", "MTX_APIADDRESS": ":59997"}, clear=False
    )
    @patch("wyzebridge.bridge_diagnostics.requests.get")
    def test_mediamtx_probe_uses_local_api_address(self, mock_get):
        response = Mock()
        response.status_code = 200
        response.raise_for_status.return_value = None
        response.json.return_value = {"name": "dog-run", "ready": True}
        mock_get.return_value = response

        result = mediamtx_probe("dog-run")

        mock_get.assert_called_once_with(
            "http://127.0.0.1:59997/v3/paths/get/dog-run", timeout=1.5
        )
        self.assertTrue(result["reachable"])
        self.assertTrue(result["enabled"])
        self.assertEqual(result["listener"], "http://127.0.0.1:59997")
        self.assertEqual(result["data"], {"name": "dog-run", "ready": True})

    @patch.dict("os.environ", {}, clear=True)
    @patch("wyzebridge.bridge_diagnostics.requests.get")
    def test_mediamtx_probe_reports_disabled_api(self, mock_get):
        result = mediamtx_probe("dog-run")

        mock_get.assert_not_called()
        self.assertFalse(result["enabled"])
        self.assertIsNone(result["reachable"])
        self.assertIn("disabled", result["error"].lower())

    @patch.dict("os.environ", {"MTX_API": "true"}, clear=False)
    @patch("wyzebridge.bridge_diagnostics.requests.get")
    def test_mediamtx_probe_defaults_to_standard_port_when_api_enabled(self, mock_get):
        response = Mock()
        response.status_code = 200
        response.raise_for_status.return_value = None
        response.json.return_value = {"items": []}
        mock_get.return_value = response

        result = mediamtx_probe(None)

        mock_get.assert_called_once_with(
            "http://127.0.0.1:9997/v3/paths/list", timeout=1.5
        )
        self.assertTrue(result["enabled"])
        self.assertTrue(result["reachable"])

    @patch("wyzebridge.bridge_diagnostics.requests.get")
    def test_whep_proxy_probe_targets_local_status_endpoint(self, mock_get):
        response = Mock()
        response.status_code = 200
        response.raise_for_status.return_value = None
        response.json.return_value = {"upstream_alive": True}
        mock_get.return_value = response

        result = whep_proxy_probe("dog-run")

        mock_get.assert_called_once_with(
            "http://127.0.0.1:8080/status/dog-run", timeout=1.5
        )
        self.assertTrue(result["reachable"])
        self.assertEqual(result["listener"], "http://127.0.0.1:8080")
        self.assertEqual(result["data"], {"upstream_alive": True})

    @patch("wyzebridge.bridge_diagnostics.requests.get")
    def test_whep_proxy_probe_requires_stream(self, mock_get):
        result = whep_proxy_probe(None)

        mock_get.assert_not_called()
        self.assertIsNone(result["reachable"])
        self.assertEqual(result["error"], "stream parameter required")


if __name__ == "__main__":
    unittest.main()

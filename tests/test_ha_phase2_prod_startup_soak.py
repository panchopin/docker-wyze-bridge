import os
import re
import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
SOAK = ROOT / "scripts" / "ha_phase2_prod_startup_soak.sh"


class TestHAPhase2ProdStartupSoak(unittest.TestCase):
    def test_script_is_shell_syntax_valid(self):
        result = subprocess.run(
            ["sh", "-n", str(SOAK)],
            cwd=ROOT,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False,
        )

        self.assertEqual(result.returncode, 0, result.stdout)

    def test_rejects_unsafe_numeric_values_before_ssh(self):
        env = os.environ.copy()
        env["HA_PHASE2_STARTUP_SECONDS"] = "60;rm"

        result = subprocess.run(
            [str(SOAK)],
            cwd=ROOT,
            env=env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False,
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Invalid HA_PHASE2_STARTUP_SECONDS", result.stdout)

    def test_rejects_unsafe_slug_values_before_ssh(self):
        env = os.environ.copy()
        env["HA_PROD_ADDON_SLUG"] = "bad;reboot"

        result = subprocess.run(
            [str(SOAK)],
            cwd=ROOT,
            env=env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False,
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Invalid HA_PROD_ADDON_SLUG", result.stdout)

    def test_rejects_pathful_bridge_urls_before_ssh(self):
        env = os.environ.copy()
        env["HA_PHASE2_BRIDGE_BASE"] = "http://172.30.32.1:5000/api?api=secret"

        result = subprocess.run(
            [str(SOAK)],
            cwd=ROOT,
            env=env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False,
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Invalid HA_PHASE2_BRIDGE_BASE", result.stdout)

    def test_static_commands_stay_read_only(self):
        script = SOAK.read_text()
        forbidden_patterns = [
            r"\bha apps stop\b",
            r"\bha apps start\b",
            r"\bha apps restart\b",
            r"\bha apps rebuild\b",
            r"\bha apps update\b",
            r"\bha apps uninstall\b",
            r"\bha host reboot\b",
            r"\bha host shutdown\b",
            r"\bcurl\b[^\n]*\b-X POST\b",
            r"\bcurl\b[^\n]*\b-X DELETE\b",
            r"\brm -rf\b",
        ]

        for pattern in forbidden_patterns:
            with self.subTest(pattern=pattern):
                self.assertIsNone(re.search(pattern, script))

    def test_api_auth_uses_header_and_output_is_sanitized(self):
        script = SOAK.read_text()

        self.assertIn('-H "api: $API_TOKEN"', script)
        self.assertNotIn("?api=$API_TOKEN", script)
        self.assertNotIn("api=$API_TOKEN", script)
        self.assertNotIn("python3 -", script)
        self.assertIn("xxd -r -p", script)
        self.assertIn('s/api=[^" ]+/api=<redacted>/g', script)

    def test_soak_checks_phase2_contract(self):
        script = SOAK.read_text()

        self.assertIn("/api/ready", script)
        self.assertIn("empty_catalog_samples", script)
        self.assertIn("native_rtsp_url_miss_samples", script)
        self.assertIn("ready_non_200", script)
        self.assertIn("ready_not_ready_samples", script)
        self.assertIn("ready_camera_lookup_error_samples", script)
        self.assertIn("ready_marker=%s", script)
        self.assertIn("camera_lookup_fallback", script)
        self.assertIn("/api/ready must report status=ready", script)
        self.assertIn("/api/ready is falling through to camera lookup", script)
        self.assertIn("empty catalog|alias refresh failed", script)
        self.assertIn("listen tcp :58888: bind: address already in use", script)


if __name__ == "__main__":
    unittest.main()

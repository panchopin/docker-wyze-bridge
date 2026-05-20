import os
import re
import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
PROBE = ROOT / "scripts" / "ha_north_yard_live_probe.sh"


class TestHANorthYardLiveProbe(unittest.TestCase):
    def test_script_is_shell_syntax_valid(self):
        result = subprocess.run(
            ["sh", "-n", str(PROBE)],
            cwd=ROOT,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False,
        )

        self.assertEqual(result.returncode, 0, result.stdout)

    def test_rejects_unsafe_camera_and_slug_values_before_ssh(self):
        env = os.environ.copy()
        env["HA_NORTH_YARD_CAMERA"] = "north-yard;reboot"

        result = subprocess.run(
            [str(PROBE)],
            cwd=ROOT,
            env=env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False,
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Invalid HA_NORTH_YARD_CAMERA", result.stdout)

        env = os.environ.copy()
        env["HA_PROD_ADDON_SLUG"] = "bad;touch-welp"

        result = subprocess.run(
            [str(PROBE)],
            cwd=ROOT,
            env=env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False,
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Invalid HA_PROD_ADDON_SLUG", result.stdout)

    def test_rejects_unsafe_count_and_url_values_before_ssh(self):
        env = os.environ.copy()
        env["HA_NORTH_YARD_PROBE_SAMPLES"] = "3;rm"

        result = subprocess.run(
            [str(PROBE)],
            cwd=ROOT,
            env=env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False,
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Invalid HA_NORTH_YARD_PROBE_SAMPLES", result.stdout)

        env = os.environ.copy()
        env["HA_NORTH_YARD_BRIDGE_BASE"] = "http://172.30.32.1:5000/path"

        result = subprocess.run(
            [str(PROBE)],
            cwd=ROOT,
            env=env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False,
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Invalid HA_NORTH_YARD_BRIDGE_BASE", result.stdout)

    def test_static_commands_stay_read_only_and_redacted(self):
        script = PROBE.read_text()
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

        self.assertNotIn("options:.data.options", script)
        self.assertIn('s/api=[^" ]+/api=<redacted>/g', script)

    def test_collects_phase1_north_yard_blocker_signals(self):
        script = PROBE.read_text()

        self.assertIn("/api/$CAMERA", script)
        self.assertIn("/api/snapshot-hashes", script)
        self.assertIn("/health/details?stream=$CAMERA", script)
        self.assertIn("/snapshot/$CAMERA.jpg", script)
        self.assertIn("/img/$CAMERA.jpg", script)
        self.assertIn("/api/frame.jpeg?src=$CAMERA", script)
        self.assertIn("/api/frame.jpeg?src=${CAMERA}-sd", script)
        self.assertIn("http://172.30.32.1:11984", script)
        self.assertIn("192.168.1.175 192.168.1.179 192.168.1.183 192.168.1.185", script)
        self.assertIn("GO2RTC_LAN_IP_OVERRIDES", script)
        self.assertIn("GO2RTC_FORCE_LAN_IP_OVERRIDES", script)
        self.assertIn("ip neigh show", script)


if __name__ == "__main__":
    unittest.main()

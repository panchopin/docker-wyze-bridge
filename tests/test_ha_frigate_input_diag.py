import os
import re
import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
DIAG = ROOT / "scripts" / "ha_frigate_input_diag.sh"


class TestHAFrigateInputDiag(unittest.TestCase):
    def test_script_is_shell_syntax_valid(self):
        result = subprocess.run(
            ["sh", "-n", str(DIAG)],
            cwd=ROOT,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False,
        )

        self.assertEqual(result.returncode, 0, result.stdout)

    def test_requires_named_cameras_before_ssh(self):
        result = subprocess.run(
            [str(DIAG)],
            cwd=ROOT,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False,
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Missing HA_FRIGATE_DIAG_CAMERAS", result.stdout)

    def test_rejects_unsafe_camera_names_before_ssh(self):
        env = os.environ.copy()
        env["HA_FRIGATE_DIAG_CAMERAS"] = "south_driveway bad;reboot"

        result = subprocess.run(
            [str(DIAG)],
            cwd=ROOT,
            env=env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False,
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Invalid camera name", result.stdout)

    def test_rejects_unsafe_slug_and_line_values_before_ssh(self):
        env = os.environ.copy()
        env["HA_FRIGATE_DIAG_CAMERAS"] = "south_driveway"
        env["HA_FRIGATE_ADDON_SLUG"] = "bad;touch-welp"

        result = subprocess.run(
            [str(DIAG)],
            cwd=ROOT,
            env=env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False,
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Invalid HA_FRIGATE_ADDON_SLUG", result.stdout)

        env = os.environ.copy()
        env["HA_FRIGATE_DIAG_CAMERAS"] = "south_driveway"
        env["HA_FRIGATE_DIAG_LOG_LINES"] = "80;rm"

        result = subprocess.run(
            [str(DIAG)],
            cwd=ROOT,
            env=env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False,
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Invalid HA_FRIGATE_DIAG_LOG_LINES", result.stdout)

    def test_static_commands_stay_read_only(self):
        script = DIAG.read_text()
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

    def test_collects_expected_frigate_and_scrypted_signals(self):
        script = DIAG.read_text()

        self.assertIn("/api/stats", script)
        self.assertIn("/api/config", script)
        self.assertIn("/api/ffprobe?paths=$encoded", script)
        self.assertIn("ha apps logs \"$FRIGATE_SLUG\"", script)
        self.assertIn("ha apps logs \"$SCRYPTED_SLUG\"", script)
        self.assertNotIn("options:.data.options", script)
        self.assertIn('s/api=[^" ]+/api=<redacted>/g', script)
        self.assertIn("<redacted>@", script)


if __name__ == "__main__":
    unittest.main()

import os
import re
import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
DOCTOR = ROOT / "scripts" / "ha_bridge_doctor.sh"


class TestHABridgeDoctor(unittest.TestCase):
    def test_script_is_shell_syntax_valid(self):
        result = subprocess.run(
            ["sh", "-n", str(DOCTOR)],
            cwd=ROOT,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False,
        )

        self.assertEqual(result.returncode, 0, result.stdout)

    def test_rejects_unsafe_slug_environment_values_before_ssh(self):
        env = os.environ.copy()
        env["HA_PROD_ADDON_SLUG"] = "bad;touch-welp"

        result = subprocess.run(
            [str(DOCTOR)],
            cwd=ROOT,
            env=env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False,
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Invalid HA_PROD_ADDON_SLUG", result.stdout)

    def test_rejects_unsafe_log_line_count_before_ssh(self):
        env = os.environ.copy()
        env["HA_BRIDGE_DOCTOR_LOG_LINES"] = "80;reboot"

        result = subprocess.run(
            [str(DOCTOR)],
            cwd=ROOT,
            env=env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False,
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Invalid HA_BRIDGE_DOCTOR_LOG_LINES", result.stdout)

    def test_static_commands_stay_read_only(self):
        script = DOCTOR.read_text()
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

    def test_static_output_is_sanitized_and_does_not_dump_options(self):
        script = DOCTOR.read_text()

        self.assertIn("option_keys:(.data.options|keys? // [])", script)
        self.assertNotIn("options:.data.options", script)
        self.assertIn('s/api=[^" ]+/api=<redacted>/g', script)
        self.assertIn("| redact", script)


if __name__ == "__main__":
    unittest.main()

import os
import re
import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
PROBE = ROOT / "scripts" / "ha_phase3_prod_sd_only_probe.sh"


class TestHAPhase3ProdSdOnlyProbe(unittest.TestCase):
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

    def test_rejects_unsafe_slug_before_ssh(self):
        env = os.environ.copy()
        env["HA_PROD_ADDON_SLUG"] = "local_docker_wyze_bridge_v4;reboot"

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

    def test_rejects_unsafe_bridge_base_before_ssh(self):
        env = os.environ.copy()
        env["HA_PHASE3_BRIDGE_BASE"] = "http://172.30.32.1:5000/path?api=secret"

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
        self.assertIn("Invalid HA_PHASE3_BRIDGE_BASE", result.stdout)

    def test_static_commands_stay_read_only(self):
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
            r"\bswap-to-dev\b",
            r"\brestore-prod\b",
        ]

        for pattern in forbidden_patterns:
            with self.subTest(pattern=pattern):
                self.assertIsNone(re.search(pattern, script))

    def test_uses_api_header_and_redacts_query_auth(self):
        script = PROBE.read_text()

        self.assertIn('-H "api: $API_TOKEN"', script)
        self.assertNotIn("?api=$API_TOKEN", script)
        self.assertIn('s/api=[^" ]+/api=<redacted>/g', script)

    def test_checks_required_phase3_production_signals(self):
        script = PROBE.read_text()

        self.assertIn(".data.options.SD_ONLY", script)
        self.assertIn("/api/$cam/stream-config", script)
        self.assertIn(".sd_only", script)
        self.assertIn(".enabled_feeds", script)
        self.assertIn(".hd_supported", script)
        self.assertIn(".hd_enabled", script)
        self.assertIn("/health/details", script)
        self.assertIn("only_sd_aliases", script)
        self.assertIn("no_main_aliases", script)
        self.assertIn("PASS: production Phase 3 SD_ONLY proof passed.", script)
        self.assertIn("FAIL: production Phase 3 SD_ONLY proof failed.", script)


if __name__ == "__main__":
    unittest.main()

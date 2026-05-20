import os
import re
import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
SOAK = ROOT / "scripts" / "ha_phase4_whep_soak.sh"


class TestHAPhase4WhepSoak(unittest.TestCase):
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

    def test_requires_named_streams_before_ssh(self):
        result = subprocess.run(
            [str(SOAK)],
            cwd=ROOT,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False,
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Missing HA_WHEP_SOAK_STREAMS", result.stdout)

    def test_rejects_unsafe_stream_names_before_ssh(self):
        env = os.environ.copy()
        env["HA_WHEP_SOAK_STREAMS"] = "deck-sub bad;reboot"

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
        self.assertIn("Invalid stream name", result.stdout)

    def test_rejects_unsafe_numeric_values_before_ssh(self):
        env = os.environ.copy()
        env["HA_WHEP_SOAK_STREAMS"] = "deck-sub"
        env["HA_WHEP_SOAK_SECONDS"] = "60;rm"

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
        self.assertIn("Invalid HA_WHEP_SOAK_SECONDS", result.stdout)

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

    def test_static_output_is_sanitized(self):
        script = SOAK.read_text()

        self.assertIn('s/api=[^" ]+/api=<redacted>/g', script)
        self.assertIn("| redact", script)

    def test_soak_checks_required_phase4_signals(self):
        script = SOAK.read_text()

        self.assertIn(".mtx_alive == true and .wyze_authed == true", script)
        self.assertIn("/health/details?stream=$stream", script)
        self.assertIn(".whep_proxy.data.video_ready == true", script)
        self.assertIn(".whep_proxy.data.has_ever_had_media == true", script)
        self.assertIn('.whep_proxy.data.upstream_state == "new"', script)
        self.assertIn(".whep_proxy.data.audio_ready == true", script)
        self.assertIn("audio_packets_seen", script)
        self.assertIn("Frigate cameras must have positive camera/process FPS", script)
        self.assertIn("1 track \\(G711\\)|audio-only|video_ready=false", script)


if __name__ == "__main__":
    unittest.main()

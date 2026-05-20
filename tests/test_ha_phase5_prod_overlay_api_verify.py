import re
import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "ha_phase5_prod_overlay_api_verify.sh"


class TestHaPhase5ProdOverlayApiVerify(unittest.TestCase):
    def run_script(self, env):
        merged_env = {
            "PATH": "/usr/bin:/bin:/usr/sbin:/sbin",
            **env,
        }
        return subprocess.run(
            [str(SCRIPT)],
            cwd=ROOT,
            env=merged_env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False,
        )

    def test_script_is_shell_syntax_valid(self):
        result = subprocess.run(
            ["sh", "-n", str(SCRIPT)],
            cwd=ROOT,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False,
        )

        self.assertEqual(result.returncode, 0, result.stdout)

    def test_invalid_slug_is_rejected_before_ssh(self):
        result = self.run_script({"HA_PROD_ADDON_SLUG": "bad slug;ha host reboot"})

        self.assertNotEqual(result.returncode, 0, result.stdout)
        self.assertIn("Invalid HA_PROD_ADDON_SLUG", result.stdout)
        self.assertNotIn("Local Overlay Build Check", result.stdout)

    def test_invalid_base_url_is_rejected_before_ssh(self):
        result = self.run_script({"HA_PHASE5_BRIDGE_BASE": "http://127.0.0.1:5000/api?api=secret"})

        self.assertNotEqual(result.returncode, 0, result.stdout)
        self.assertIn("Invalid HA_PHASE5_BRIDGE_BASE", result.stdout)
        self.assertNotIn("Local Overlay Build Check", result.stdout)

    def test_script_is_read_only_and_non_disruptive(self):
        script = SCRIPT.read_text(encoding="utf-8")
        forbidden_command_patterns = [
            r"\bha apps stop\b",
            r"\bha apps start\b",
            r"\bha apps restart\b",
            r"\bha apps rebuild\b",
            r"\bha apps uninstall\b",
            r"\bha host reboot\b",
            r"\bsupervisor/addons/[^/]+/(stop|start|restart|rebuild|uninstall)\b",
            r"\brm\s+-rf\b",
        ]

        for pattern in forbidden_command_patterns:
            with self.subTest(pattern=pattern):
                self.assertIsNone(
                    re.search(pattern, script),
                    f"forbidden command pattern matched script: {pattern}",
                )

    def test_supervisor_output_stays_sanitized(self):
        script = SCRIPT.read_text(encoding="utf-8")

        self.assertIn("option_keys:(.data.options|keys? // [])", script)
        self.assertIn("WB_API // .data.options.wb_api", script)
        self.assertNotIn("cat /data/options.json", script)
        self.assertNotIn("jq .data.options", script)

    def test_uses_api_header_not_query_string(self):
        script = SCRIPT.read_text(encoding="utf-8")

        self.assertIn('-H "api: $API_TOKEN"', script)
        self.assertNotIn("?api=", script)

    def test_requires_identity_health_catalog_ready_and_logs(self):
        script = SCRIPT.read_text(encoding="utf-8")

        expected_snippets = [
            '"$ROOT_DIR/scripts/build.sh" --check',
            "production add-on state must be started",
            "HA_PHASE5_EXPECTED_REPOSITORY",
            "HA_PHASE5_EXPECTED_VERSION",
            ".mtx_alive == true and .wyze_authed == true",
            "/api camera catalog must meet HA_PHASE5_MIN_CAMERAS",
            "every enabled camera must expose native_rtsp_url",
            "/api/ready must report status=ready",
            "ready_body_keys",
            "camera_lookup_fallback",
            "production /api/ready is falling through to camera lookup",
            "listen tcp :58888: bind: address already in use",
            "1 track \\(G711\\)|audio-only|video_ready=false|upstream_state=\"new\"",
            "PASS: production Phase 5 overlay/API proof passed.",
            "FAIL: production Phase 5 overlay/API proof failed.",
        ]

        for snippet in expected_snippets:
            with self.subTest(snippet=snippet):
                self.assertIn(snippet, script)


if __name__ == "__main__":
    unittest.main()

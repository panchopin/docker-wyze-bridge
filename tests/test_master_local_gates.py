import re
import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
LOCAL_GATES = ROOT / "scripts" / "run_master_local_gates.sh"


class TestMasterLocalGates(unittest.TestCase):
    def test_script_is_shell_syntax_valid(self):
        result = subprocess.run(
            ["sh", "-n", str(LOCAL_GATES)],
            cwd=ROOT,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False,
        )

        self.assertEqual(result.returncode, 0, result.stdout)

    def test_script_runs_required_non_live_master_gates(self):
        script = LOCAL_GATES.read_text()

        expected_snippets = [
            "./scripts/build.sh --check",
            "tests/test_go2rtc_snapshot_and_diagnostics.py",
            "tests/test_preview_validation.py",
            "tests/test_thumbnail_404_logging.py",
            "tests/test_ha_addon_packaging.py",
            "tests/test_ha_bridge_doctor.py",
            "tests/test_ha_frigate_input_diag.py",
            "tests/test_ha_north_yard_live_probe.py",
            "tests/test_ha_phase3_dead_branch_audit.py",
            "tests/test_ha_phase3_prod_sd_only_probe.py",
            "tests/test_ha_phase2_prod_startup_soak.py",
            "tests/test_ha_phase4_whep_soak.py",
            "tests/test_ha_phase5_prod_overlay_api_verify.py",
            "tests/test_ha_prod_recovery_verify.py",
            "go test ./whep_proxy/... -v -count=1",
            "python3 -m pytest -q --tb=short --timeout=20",
        ]

        for snippet in expected_snippets:
            with self.subTest(snippet=snippet):
                self.assertIn(snippet, script)

    def test_script_stays_local_and_non_disruptive(self):
        script = LOCAL_GATES.read_text()
        forbidden_patterns = [
            r"\./scripts/ha_ssh\.sh\b",
            r"\bha apps\b",
            r"\bha host\b",
            r"\bswap-to-dev\b",
            r"\brestore-prod\b",
            r"\bha_bridge_doctor\.sh\s*$",
            r"\breboot\b",
            r"\buninstall\b",
            r"\brm -rf\b",
        ]

        for pattern in forbidden_patterns:
            with self.subTest(pattern=pattern):
                self.assertIsNone(re.search(pattern, script, re.MULTILINE))


if __name__ == "__main__":
    unittest.main()

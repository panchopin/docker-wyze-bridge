import os
import re
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
AUDIT = ROOT / "scripts" / "ha_phase3_dead_branch_audit.sh"


class TestHAPhase3DeadBranchAudit(unittest.TestCase):
    def test_script_is_shell_syntax_valid(self):
        result = subprocess.run(
            ["sh", "-n", str(AUDIT)],
            cwd=ROOT,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False,
        )

        self.assertEqual(result.returncode, 0, result.stdout)

    def test_static_commands_stay_local_and_read_only(self):
        script = AUDIT.read_text()
        forbidden_patterns = [
            r"\./scripts/ha_ssh\.sh\b",
            r"\bha apps\b",
            r"\bha host\b",
            r"\bcurl\b",
            r"\bswap-to-dev\b",
            r"\brestore-prod\b",
            r"\breboot\b",
            r"\buninstall\b",
            r"\brm -rf\b",
            r"\bmv\b",
            r"\bcp\b",
            r"\brsync\b",
        ]

        for pattern in forbidden_patterns:
            with self.subTest(pattern=pattern):
                self.assertIsNone(re.search(pattern, script))

    def test_missing_prod_proof_writes_failing_artifact(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "tmp").mkdir()
            env = os.environ.copy()
            env["PHASE3_AUDIT_ROOT"] = str(root)

            result = subprocess.run(
                [str(AUDIT)],
                cwd=ROOT,
                env=env,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                check=False,
            )

            self.assertNotEqual(result.returncode, 0)
            self.assertIn(
                "FAIL: production Phase 3 SD_ONLY proof must pass before dead HD/feed branches can be removed.",
                result.stdout,
            )
            self.assertIn("FAIL: Phase 3 dead branch audit failed.", result.stdout)
            artifacts = sorted((root / "tmp").glob("phase3_dead_branch_audit_*.txt"))
            self.assertEqual(len(artifacts), 1)
            self.assertIn(
                "FAIL: Phase 3 dead branch audit failed.",
                artifacts[0].read_text(),
            )

    def test_passes_on_clean_tree_with_prod_proof(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "tmp").mkdir()
            (root / "app").mkdir()
            (root / "runtime_overlays").mkdir()
            (root / "app" / "feed.py").write_text("stream = 'sd'\n")
            (root / "tmp" / "phase3_prod_sd_only_20260519_235959.txt").write_text(
                "PASS: production Phase 3 SD_ONLY proof passed.\n"
            )
            env = os.environ.copy()
            env["PHASE3_AUDIT_ROOT"] = str(root)

            result = subprocess.run(
                [str(AUDIT)],
                cwd=ROOT,
                env=env,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                check=False,
            )

            self.assertEqual(result.returncode, 0, result.stdout)
            self.assertIn("PASS: Phase 3 dead branch audit passed.", result.stdout)
            self.assertIn("hd_opt_in_branch_status=reviewed", result.stdout)

    def test_fails_on_legacy_quality_knobs_in_canonical_or_overlay_sources(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "tmp").mkdir()
            (root / "app").mkdir()
            (root / "runtime_overlays" / "home_assistant").mkdir(parents=True)
            (root / "app" / "feed.py").write_text("stream = 'sd'\n")
            (root / "runtime_overlays" / "home_assistant" / "config.yml").write_text(
                "schema:\n  QUALITY: str?\n"
            )
            (root / "tmp" / "phase3_prod_sd_only_20260519_235959.txt").write_text(
                "PASS: production Phase 3 SD_ONLY proof passed.\n"
            )
            env = os.environ.copy()
            env["PHASE3_AUDIT_ROOT"] = str(root)

            result = subprocess.run(
                [str(AUDIT)],
                cwd=ROOT,
                env=env,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                check=False,
            )

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("legacy_match:", result.stdout)
            self.assertIn("FAIL: legacy quality/bitrate knobs remain", result.stdout)


if __name__ == "__main__":
    unittest.main()

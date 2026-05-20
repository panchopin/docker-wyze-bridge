import json
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
STATUS = ROOT / "scripts" / "master_goal_status.py"


class TestMasterGoalStatus(unittest.TestCase):
    def make_root(self) -> Path:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        proof_dir = root / "tmp"
        proof_dir.mkdir()

        phase1 = proof_dir / "phase1_snapshot_soak_dev_quiet_20260518_092953"
        phase1.mkdir()
        (phase1 / "aggregate.json").write_text(
            json.dumps(
                {
                    "samples": 61,
                    "all_samples_ok": True,
                    "all_cameras_changed": True,
                    "per_cam": {"deck-sub": {"failures": 0}},
                }
            ),
            encoding="utf-8",
        )
        (phase1 / "phase1_soak_proof_screenshot.png").write_bytes(b"png")

        (proof_dir / "phase2_startup_soak_proof_20260518.md").write_text(
            "\n".join(
                [
                    "`/api` non-200 samples: `0`",
                    "`/api/ready` non-200 samples: `0`",
                    "empty catalog samples: `0`",
                    "`min_camera_count`: `6`",
                    "`max_camera_count`: `6`",
                ]
            ),
            encoding="utf-8",
        )
        (
            proof_dir
            / "phase2_prod_startup_soak_pre_recovery_20260518_184506.txt"
        ).write_text(
            "\n".join(
                [
                    "sample=1 ready_marker=camera_lookup_fallback",
                    "ready_camera_lookup_error_samples=14",
                    "FAIL: /api/ready is falling through to camera lookup instead of the readiness route",
                    "FAIL: production Phase 2 startup/API soak failed.",
                ]
            ),
            encoding="utf-8",
        )
        (proof_dir / "phase3_sd_only_live_proof_20260518.md").write_text(
            "\n".join(
                [
                    "Phase 3 is green for the live Home Assistant dev lane.",
                    '"all_sd_only": true',
                    '"all_one_feed": true',
                    '"no_hd_supported": true',
                    '"no_hd_enabled": true',
                    '"status_code": 409',
                    '"only_sd_aliases": true',
                    '"no_main_aliases": true',
                ]
            ),
            encoding="utf-8",
        )
        (proof_dir / "master_goal_gate_audit_20260518.md").write_text(
            "\n".join(
                [
                    "home_assistant: matches canonical app + overlay",
                    "go test ./whep_proxy/...: PASS",
                    "run_master_local_gates: PASS",
                    "whep_proxy/` is now canonical",
                ]
            ),
            encoding="utf-8",
        )
        (proof_dir / "prod_mtx_58888_blocker_20260518.md").write_text(
            '{"mtx_alive": false}\nlisten tcp :58888: bind: address already in use',
            encoding="utf-8",
        )
        (proof_dir / "ha_prod_recovery_verify_pre_recovery_20260518_173541.txt").write_text(
            "FAIL: production bridge is not ready for the remaining live Phase 4/5 gates.",
            encoding="utf-8",
        )
        (
            proof_dir
            / "phase5_prod_overlay_api_verify_pre_recovery_20260518_194314.txt"
        ).write_text(
            "\n".join(
                [
                    "ready_marker=camera_lookup_fallback ready_body_keys=error",
                    "FAIL: production /api/ready is falling through to camera lookup; overlay-built readiness route is not live",
                    "FAIL: production Phase 5 overlay/API proof failed.",
                ]
            ),
            encoding="utf-8",
        )
        (proof_dir / "phase4_whep_soak_pre_recovery_20260518_174012.txt").write_text(
            "FAIL: Phase 4 WHEP soak failed.",
            encoding="utf-8",
        )
        (proof_dir / "ha_bridge_doctor_20260518_171010.txt").write_text(
            "## Frigate FPS\nsouth_driveway\t10.0\t10.0\t0.0",
            encoding="utf-8",
        )
        return root

    def make_complete_root(self) -> Path:
        root = self.make_root()
        proof_dir = root / "tmp"
        (proof_dir / "prod_mtx_58888_blocker_20260518.md").write_text(
            '{"mtx_alive": true, "wyze_authed": true}\n[HLS] listener opened on :58888',
            encoding="utf-8",
        )
        (proof_dir / "ha_bridge_doctor_20260519_235959.txt").write_text(
            "\n".join(
                [
                    "## Production Health",
                    '{"mtx_alive": true, "wyze_authed": true, "active_streams": 5}',
                    "## MediaMTX / Bridge Log Tail",
                    "2026/05/19 INF [HLS] listener opened on :58888",
                    "## Frigate FPS",
                    "south_driveway\t10.0\t10.0\t0.0",
                ]
            ),
            encoding="utf-8",
        )
        (proof_dir / "phase1_prod_snapshot_soak_20260519_235959.txt").write_text(
            "PASS: production Phase 1 snapshot soak passed.",
            encoding="utf-8",
        )
        (proof_dir / "phase2_prod_startup_soak_20260519_235959.txt").write_text(
            "PASS: production Phase 2 startup/API soak passed.",
            encoding="utf-8",
        )
        (proof_dir / "phase3_prod_sd_only_20260519_235959.txt").write_text(
            "PASS: production Phase 3 SD_ONLY proof passed.",
            encoding="utf-8",
        )
        (proof_dir / "phase3_dead_branch_audit_20260519_235959.txt").write_text(
            "PASS: Phase 3 dead branch audit passed.",
            encoding="utf-8",
        )
        (proof_dir / "phase4_whep_soak_20260519_235959.txt").write_text(
            "\n".join(
                [
                    "duration_seconds=3600",
                    "## Sample 121 elapsed=3600s",
                    "PASS: Phase 4 WHEP soak passed for all named streams.",
                ]
            ),
            encoding="utf-8",
        )
        (proof_dir / "phase4_whep_wedge_injection_20260519_235959.txt").write_text(
            "PASS: Phase 4 WHEP wedge injection proof passed.",
            encoding="utf-8",
        )
        (proof_dir / "ha_prod_recovery_verify_20260519_235959.txt").write_text(
            "PASS: production bridge is recovered enough to resume the remaining live Phase 4/5 gates.",
            encoding="utf-8",
        )
        (proof_dir / "phase5_prod_overlay_api_verify_20260519_235959.txt").write_text(
            "PASS: production Phase 5 overlay/API proof passed.",
            encoding="utf-8",
        )
        return root

    def test_json_status_reports_blocked_with_expected_phase_states(self):
        root = self.make_root()
        result = subprocess.run(
            [str(STATUS), "--root", str(root), "--json"],
            cwd=ROOT,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False,
        )

        self.assertEqual(result.returncode, 0, result.stdout)
        data = json.loads(result.stdout)
        self.assertEqual(data["overall"], "blocked")
        phases = {phase["phase"]: phase["status"] for phase in data["phases"]}
        self.assertEqual(phases["Phase 1 snapshot pipeline"], "green-dev")
        self.assertEqual(phases["Phase 2 startup readiness"], "blocked")
        self.assertEqual(phases["Phase 3 SD_ONLY model"], "green-dev")
        self.assertEqual(phases["Phase 4 WHEP proxy"], "blocked")
        self.assertEqual(phases["Phase 5 three-tree consolidation"], "blocked")
        phase_evidence = {
            phase["phase"]: "\n".join(phase["evidence"])
            for phase in data["phases"]
        }
        self.assertIn(
            "production startup/API soak failed",
            phase_evidence["Phase 2 startup readiness"],
        )
        self.assertIn(
            "ready_camera_lookup_error_samples=14",
            phase_evidence["Phase 2 startup readiness"],
        )
        self.assertIn(
            "ready_marker=camera_lookup_fallback",
            phase_evidence["Phase 2 startup readiness"],
        )
        self.assertIn("live WHEP soak failed", phase_evidence["Phase 4 WHEP proxy"])
        self.assertIn(
            "production recovery verifier failed",
            phase_evidence["Phase 5 three-tree consolidation"],
        )
        self.assertIn(
            "production overlay/API verifier failed",
            phase_evidence["Phase 5 three-tree consolidation"],
        )
        self.assertIn(
            "ready_marker=camera_lookup_fallback",
            phase_evidence["Phase 5 three-tree consolidation"],
        )

    def test_markdown_status_is_plainly_blocked(self):
        root = self.make_root()
        result = subprocess.run(
            [str(STATUS), "--root", str(root)],
            cwd=ROOT,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False,
        )

        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn("overall: blocked", result.stdout)
        self.assertIn("MediaMTX logs show :58888 bind conflict", result.stdout)

    def test_strict_mode_fails_when_blocked(self):
        root = self.make_root()
        result = subprocess.run(
            [str(STATUS), "--root", str(root), "--strict"],
            cwd=ROOT,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False,
        )

        self.assertEqual(result.returncode, 1, result.stdout)

    def test_doctor_without_blocker_symptoms_does_not_make_overall_blocked(self):
        root = self.make_root()
        proof_dir = root / "tmp"
        (proof_dir / "prod_mtx_58888_blocker_20260518.md").unlink()
        (proof_dir / "ha_bridge_doctor_20260518_171010.txt").write_text(
            "\n".join(
                [
                    "## Production Health",
                    '{"mtx_alive": true, "wyze_authed": true}',
                    "## MediaMTX / Bridge Log Tail",
                    "2026/05/18 INF [HLS] listener opened on :58888",
                    "## Frigate FPS",
                    "south_driveway\t10.0\t10.0\t0.0",
                ]
            ),
            encoding="utf-8",
        )

        result = subprocess.run(
            [str(STATUS), "--root", str(root), "--json"],
            cwd=ROOT,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False,
        )

        self.assertEqual(result.returncode, 0, result.stdout)
        data = json.loads(result.stdout)
        self.assertEqual(data["overall"], "incomplete")
        self.assertNotIn(
            "production health reports mtx_alive=false",
            data["blocker_evidence"],
        )
        self.assertNotIn(
            "MediaMTX logs show :58888 bind conflict",
            data["blocker_evidence"],
        )
        self.assertTrue(
            any(item.startswith("latest doctor output:") for item in data["blocker_evidence"])
        )

    def test_latest_healthy_doctor_overrides_stale_blocker_file(self):
        root = self.make_root()
        proof_dir = root / "tmp"
        (proof_dir / "ha_bridge_doctor_20260519_235959.txt").write_text(
            "\n".join(
                [
                    "## Production Health",
                    '{"mtx_alive": true, "wyze_authed": true}',
                    "## MediaMTX / Bridge Log Tail",
                    "2026/05/19 INF [HLS] listener opened on :58888",
                    "## Frigate FPS",
                    "south_driveway\t10.0\t10.0\t0.0",
                ]
            ),
            encoding="utf-8",
        )

        result = subprocess.run(
            [str(STATUS), "--root", str(root), "--json"],
            cwd=ROOT,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False,
        )

        self.assertEqual(result.returncode, 0, result.stdout)
        data = json.loads(result.stdout)
        self.assertEqual(data["overall"], "incomplete")
        self.assertNotIn(
            "production health reports mtx_alive=false",
            data["blocker_evidence"],
        )
        self.assertNotIn(
            "MediaMTX logs show :58888 bind conflict",
            data["blocker_evidence"],
        )

    def test_latest_recovery_pass_overrides_older_unhealthy_doctor(self):
        root = self.make_root()
        proof_dir = root / "tmp"
        doctor = proof_dir / "ha_bridge_doctor_20260520_061625.txt"
        doctor.write_text(
            "\n".join(
                [
                    "## Production Health",
                    '{"mtx_alive": false, "wyze_authed": true}',
                    "## MediaMTX / Bridge Log Tail",
                    "listen tcp :58888: bind: address already in use",
                ]
            ),
            encoding="utf-8",
        )
        recovery = proof_dir / "ha_prod_recovery_verify_20260520_061943.txt"
        recovery.write_text(
            "PASS: production bridge is recovered enough to resume the remaining live Phase 4/5 gates.",
            encoding="utf-8",
        )

        result = subprocess.run(
            [str(STATUS), "--root", str(root), "--json"],
            cwd=ROOT,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False,
        )

        self.assertEqual(result.returncode, 0, result.stdout)
        data = json.loads(result.stdout)
        self.assertEqual(data["overall"], "incomplete")
        self.assertNotIn(
            "production health reports mtx_alive=false",
            data["blocker_evidence"],
        )
        self.assertTrue(
            any(item.startswith("latest recovery verifier output:") for item in data["blocker_evidence"])
        )

    def test_single_blocker_symptom_is_not_enough_for_overall_blocked(self):
        root = self.make_root()
        proof_dir = root / "tmp"
        (proof_dir / "prod_mtx_58888_blocker_20260518.md").write_text(
            '{"mtx_alive": false}',
            encoding="utf-8",
        )
        (proof_dir / "ha_bridge_doctor_20260518_171010.txt").write_text(
            "## Frigate FPS\nsouth_driveway\t10.0\t10.0\t0.0",
            encoding="utf-8",
        )

        result = subprocess.run(
            [str(STATUS), "--root", str(root), "--json"],
            cwd=ROOT,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False,
        )

        self.assertEqual(result.returncode, 0, result.stdout)
        data = json.loads(result.stdout)
        self.assertEqual(data["overall"], "incomplete")
        self.assertIn(
            "production health reports mtx_alive=false",
            data["blocker_evidence"],
        )
        self.assertNotIn(
            "MediaMTX logs show :58888 bind conflict",
            data["blocker_evidence"],
        )

    def test_dev_green_without_production_artifacts_is_not_complete(self):
        root = self.make_root()
        proof_dir = root / "tmp"
        for pattern in [
            "phase2_prod_startup_soak_*.txt",
            "phase4_whep_soak_*.txt",
            "ha_prod_recovery_verify_*.txt",
            "phase5_prod_overlay_api_verify_*.txt",
        ]:
            for path in proof_dir.glob(pattern):
                path.unlink()
        (proof_dir / "prod_mtx_58888_blocker_20260518.md").write_text(
            '{"mtx_alive": true, "wyze_authed": true}',
            encoding="utf-8",
        )
        (proof_dir / "ha_bridge_doctor_20260518_171010.txt").write_text(
            "## Frigate FPS\nsouth_driveway\t10.0\t10.0\t0.0",
            encoding="utf-8",
        )

        result = subprocess.run(
            [str(STATUS), "--root", str(root), "--json"],
            cwd=ROOT,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False,
        )

        self.assertEqual(result.returncode, 0, result.stdout)
        data = json.loads(result.stdout)
        self.assertEqual(data["overall"], "incomplete")
        phases = {phase["phase"]: phase["status"] for phase in data["phases"]}
        self.assertNotIn("complete", phases.values())

    def test_phase1_blocker_includes_north_yard_live_clues(self):
        root = self.make_root()
        proof_dir = root / "tmp"
        (proof_dir / "phase1_prod_snapshot_soak_20260519_080903.txt").write_text(
            "FAIL: production Phase 1 snapshot soak failed.",
            encoding="utf-8",
        )
        (proof_dir / "north_yard_authed_snapshot_reprobe_20260519_104249.txt").write_text(
            "\n".join(
                [
                    "snapshot_attempt=1 code=000000 bytes=0 sha= kind=",
                    "img_attempt=1 code=200 bytes=130294 sha=abc kind=JPEG image data",
                    "img_attempt=2 code=200 bytes=130294 sha=abc kind=JPEG image data",
                    '"source": "wyze-api"',
                ]
            ),
            encoding="utf-8",
        )
        (proof_dir / "north_yard_lan_sweep_20260519_104441.txt").write_text(
            "\n".join(
                [
                    "ip=192.168.1.183 ping=down neigh=<none>",
                    "ip=192.168.1.185 ping=down neigh=<none>",
                ]
            ),
            encoding="utf-8",
        )

        result = subprocess.run(
            [str(STATUS), "--root", str(root), "--json"],
            cwd=ROOT,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False,
        )

        self.assertEqual(result.returncode, 0, result.stdout)
        data = json.loads(result.stdout)
        phase1 = next(
            phase
            for phase in data["phases"]
            if phase["phase"] == "Phase 1 snapshot pipeline"
        )
        evidence = "\n".join(phase1["evidence"])
        self.assertEqual(phase1["status"], "blocked")
        self.assertIn("north-yard forced snapshot timed out", evidence)
        self.assertIn("north-yard cached image hash did not change", evidence)
        self.assertIn("north-yard snapshot registry source is wyze-api", evidence)
        self.assertIn("configured north-yard IP 192.168.1.183 is unreachable", evidence)
        self.assertIn("override north-yard IP 192.168.1.185 is unreachable", evidence)

    def test_phase1_blocker_reads_current_north_yard_reprobe_artifact(self):
        root = self.make_root()
        proof_dir = root / "tmp"
        (proof_dir / "phase1_prod_snapshot_soak_20260519_080903.txt").write_text(
            "FAIL: production Phase 1 snapshot soak failed.",
            encoding="utf-8",
        )
        (proof_dir / "north_yard_current_reprobe_20260519_121836.txt").write_text(
            "\n".join(
                [
                    'route=/api/north-yard code=200 bytes=2154 mime=unknown sha256=aaa',
                    '{"snapshot_source":"go2rtc"}',
                    'route=/api/snapshot-hashes code=200 bytes=1240 mime=unknown sha256=bbb',
                    '{"registry":{"north-yard":{"source":"wyze-api"}}}',
                    'route=/snapshot/north-yard.jpg code=000 bytes=0 mime=<none> sha256=<none>',
                    'route=/img/north-yard.jpg code=200 bytes=128283 mime=unknown sha256=abc',
                    'route=/img/north-yard.jpg code=200 bytes=128283 mime=unknown sha256=abc',
                    '192.168.1.183\tunreachable',
                    '192.168.1.185\tunreachable',
                ]
            ),
            encoding="utf-8",
        )

        result = subprocess.run(
            [str(STATUS), "--root", str(root), "--json"],
            cwd=ROOT,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False,
        )

        self.assertEqual(result.returncode, 0, result.stdout)
        data = json.loads(result.stdout)
        phase1 = next(
            phase
            for phase in data["phases"]
            if phase["phase"] == "Phase 1 snapshot pipeline"
        )
        evidence = "\n".join(phase1["evidence"])
        self.assertEqual(phase1["status"], "blocked")
        self.assertIn("north-yard forced snapshot timed out", evidence)
        self.assertIn("north-yard cached image hash did not change", evidence)
        self.assertIn("north-yard snapshot registry source is wyze-api", evidence)
        self.assertIn("configured north-yard IP 192.168.1.183 is unreachable", evidence)
        self.assertIn("override north-yard IP 192.168.1.185 is unreachable", evidence)

    def test_phase1_current_reprobe_supersedes_older_lan_sweep(self):
        root = self.make_root()
        proof_dir = root / "tmp"
        (proof_dir / "phase1_prod_snapshot_soak_20260519_080903.txt").write_text(
            "FAIL: production Phase 1 snapshot soak failed.",
            encoding="utf-8",
        )
        (proof_dir / "north_yard_current_reprobe_20260519_175229.txt").write_text(
            "\n".join(
                [
                    'route=/api/north-yard code=200 bytes=2154 mime=unknown sha256=aaa',
                    '{"snapshot_source":"go2rtc"}',
                    'route=/api/snapshot-hashes code=200 bytes=1240 mime=unknown sha256=bbb',
                    '{"registry":{"north-yard":{"source":"wyze-api"}}}',
                    "## Frame Samples",
                    'route=/snapshot/north-yard.jpg code=000000 bytes=0 mime=<none> sha256=<none>',
                    'route=/img/north-yard.jpg code=200 bytes=126953 mime=unknown sha256=abc',
                    'url=http://127.0.0.1:11984/api/frame.jpeg?src=north-yard code=000000 bytes=0 mime=<none> sha256=<none>',
                    'url=http://127.0.0.1:11984/api/frame.jpeg?src=north-yard-sd code=000000 bytes=0 mime=<none> sha256=<none>',
                    "## LAN Reachability",
                    '192.168.1.183\treachable',
                    '192.168.1.185\tunreachable',
                ]
            ),
            encoding="utf-8",
        )
        (proof_dir / "north_yard_lan_sweep_20260519_104441.txt").write_text(
            "\n".join(
                [
                    "ip=192.168.1.183 ping=down neigh=<none>",
                    "ip=192.168.1.185 ping=down neigh=<none>",
                ]
            ),
            encoding="utf-8",
        )

        result = subprocess.run(
            [str(STATUS), "--root", str(root), "--json"],
            cwd=ROOT,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False,
        )

        self.assertEqual(result.returncode, 0, result.stdout)
        data = json.loads(result.stdout)
        phase1 = next(
            phase
            for phase in data["phases"]
            if phase["phase"] == "Phase 1 snapshot pipeline"
        )
        evidence = "\n".join(phase1["evidence"])
        self.assertEqual(phase1["status"], "blocked")
        self.assertIn("north-yard forced snapshot timed out", evidence)
        self.assertIn("north-yard go2rtc main frame route returned no bytes", evidence)
        self.assertIn("north-yard go2rtc SD frame route returned no bytes", evidence)
        self.assertNotIn("configured north-yard IP 192.168.1.183 is unreachable", evidence)
        self.assertIn("configured/current north-yard IP 192.168.1.183 is reachable", evidence)
        self.assertIn("override north-yard IP 192.168.1.185 is unreachable", evidence)
        self.assertIn(
            "North Yard authenticated snapshot must stop timing out",
            phase1["remaining"],
        )
        self.assertIn(
            "North Yard go2rtc main frame must return a non-empty JPEG",
            phase1["remaining"],
        )
        self.assertIn(
            "North Yard go2rtc SD frame must return a non-empty JPEG",
            phase1["remaining"],
        )
        self.assertIn(
            "stale North Yard LAN override must stop replacing the reachable helper/current IP",
            phase1["remaining"],
        )
        self.assertNotIn("Production snapshot soak proof is still required", phase1["remaining"])

    def test_phase1_current_reprobe_ignores_stale_direct_go2rtc_probe_when_bridge_snapshots_change(self):
        root = self.make_root()
        proof_dir = root / "tmp"
        (proof_dir / "phase1_prod_snapshot_soak_20260519_080903.txt").write_text(
            "FAIL: production Phase 1 snapshot soak failed.",
            encoding="utf-8",
        )
        (proof_dir / "north_yard_current_reprobe_20260520_062445.txt").write_text(
            "\n".join(
                [
                    '{"snapshot_source":"go2rtc","native_alias":"north-yard-sd"}',
                    '{"bytes":36691,"source":"go2rtc:north-yard-sd"}',
                    "## Frame Samples",
                    'route=/snapshot/north-yard.jpg code=200 bytes=36763 mime=unknown sha256=aaa',
                    'route=/img/north-yard.jpg code=200 bytes=36763 mime=unknown sha256=aaa',
                    'url=http://127.0.0.1:11984/api/frame.jpeg?src=north-yard code=000000 bytes=0 mime=<none> sha256=<none>',
                    'url=http://127.0.0.1:11984/api/frame.jpeg?src=north-yard-sd code=000000 bytes=0 mime=<none> sha256=<none>',
                    'route=/snapshot/north-yard.jpg code=200 bytes=36741 mime=unknown sha256=bbb',
                    'route=/img/north-yard.jpg code=200 bytes=36741 mime=unknown sha256=bbb',
                    "## LAN Reachability",
                    '192.168.1.183\treachable',
                    '192.168.1.185\tunreachable',
                ]
            ),
            encoding="utf-8",
        )

        result = subprocess.run(
            [str(STATUS), "--root", str(root), "--json"],
            cwd=ROOT,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False,
        )

        self.assertEqual(result.returncode, 0, result.stdout)
        data = json.loads(result.stdout)
        phase1 = next(
            phase
            for phase in data["phases"]
            if phase["phase"] == "Phase 1 snapshot pipeline"
        )
        evidence = "\n".join(phase1["evidence"])
        self.assertEqual(phase1["status"], "blocked")
        self.assertNotIn("north-yard forced snapshot timed out", evidence)
        self.assertNotIn("north-yard cached image hash did not change", evidence)
        self.assertNotIn("north-yard snapshot registry source is wyze-api", evidence)
        self.assertNotIn("north-yard go2rtc main frame route returned no bytes", evidence)
        self.assertNotIn("north-yard go2rtc SD frame route returned no bytes", evidence)
        self.assertIn("configured/current north-yard IP 192.168.1.183 is reachable", evidence)
        self.assertIn("override north-yard IP 192.168.1.185 is unreachable", evidence)

    def test_frigate_strict_monitor_failure_blocks_phase4_until_full_soak_passes(self):
        root = self.make_root()
        proof_dir = root / "tmp"
        (proof_dir / "phase4_whep_soak_pre_recovery_20260518_174012.txt").unlink()
        (proof_dir / "frigate_skipped_fps_monitor_20260519_103241.txt").write_text(
            "\n".join(
                [
                    "north_driveway\t10.1\t10.0\t0.1",
                    "BAD=north_driveway",
                    "FAIL: Frigate FPS had one or more strict-gate blips.",
                ]
            ),
            encoding="utf-8",
        )

        result = subprocess.run(
            [str(STATUS), "--root", str(root), "--json"],
            cwd=ROOT,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False,
        )

        self.assertEqual(result.returncode, 0, result.stdout)
        data = json.loads(result.stdout)
        phase4 = next(
            phase for phase in data["phases"] if phase["phase"] == "Phase 4 WHEP proxy"
        )
        self.assertEqual(phase4["status"], "blocked")
        self.assertIn("Frigate strict FPS monitor failed", "\n".join(phase4["evidence"]))

    def test_phase4_soak_frigate_strict_failure_marks_live_soak_failed(self):
        root = self.make_root()
        proof_dir = root / "tmp"
        (proof_dir / "phase4_whep_soak_pre_recovery_20260518_174012.txt").unlink()
        (proof_dir / "phase4_whep_soak_20260519_122635.txt").write_text(
            "\n".join(
                [
                    "south_driveway\t10.1\t10.0\t0.1",
                    "Unhealthy Frigate cameras:",
                    "south_driveway",
                    "FAIL: Frigate cameras must have positive camera/process FPS and skipped_fps=0",
                ]
            ),
            encoding="utf-8",
        )

        result = subprocess.run(
            [str(STATUS), "--root", str(root), "--json"],
            cwd=ROOT,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False,
        )

        self.assertEqual(result.returncode, 0, result.stdout)
        data = json.loads(result.stdout)
        phase4 = next(
            phase for phase in data["phases"] if phase["phase"] == "Phase 4 WHEP proxy"
        )
        self.assertEqual(phase4["status"], "blocked")
        evidence = "\n".join(phase4["evidence"])
        self.assertIn("live WHEP soak failed", evidence)
        self.assertIn(
            "Frigate strict FPS failed for south_driveway "
            "(camera_fps=10.1, process_fps=10.0, skipped_fps=0.1)",
            evidence,
        )

    def test_phase4_soak_frigate_strict_failure_names_latest_camera(self):
        root = self.make_root()
        proof_dir = root / "tmp"
        (proof_dir / "phase4_whep_soak_pre_recovery_20260518_174012.txt").unlink()
        (proof_dir / "phase4_whep_soak_20260519_152933.txt").write_text(
            "\n".join(
                [
                    "south_driveway\t10.0\t9.5\t0.0",
                    "north_driveway\t10.1\t9.6\t0.2",
                    "doorbell\t10.0\t9.4\t0.0",
                    "Unhealthy Frigate cameras:",
                    "north_driveway",
                    "FAIL: Frigate cameras must have positive camera/process FPS and skipped_fps=0",
                    "",
                    "## Sample 11 elapsed=303s",
                    "north_driveway\t10.1\t10.0\t0.0",
                ]
            ),
            encoding="utf-8",
        )
        (proof_dir / "frigate_input_diag_north_driveway_20260519_153516.txt").write_text(
            "\n".join(
                [
                    "## Frigate/Scrypted Input Diagnostic",
                    "cameras=north_driveway",
                    "",
                    "## Current Frigate Stats",
                    "north_driveway\t10.1\t10.1\t0.0\t1202\t898",
                    "",
                    "## Camera north_driveway FFprobe",
                    'path=rtsp://192.168.1.244:44095/a3ea1612e8a0a713',
                    '[{"return_code":0,"stderr":[],"stdout":{"streams":[]}}]',
                    'path=rtsp://192.168.1.244:44095/ac3d9badc30004af',
                    '[{"return_code":0,"stderr":[],"stdout":{"streams":[]}}]',
                    "",
                    "## Recent Scrypted RTSP Logs",
                    "[North Driveway E1 Pro] response headers RTSP/1.0 200 OK",
                    "RTP-Info: url=rtsp://192.168.1.244:44095/ac3d9badc30004af/track1",
                ]
            ),
            encoding="utf-8",
        )

        result = subprocess.run(
            [str(STATUS), "--root", str(root), "--json"],
            cwd=ROOT,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False,
        )

        self.assertEqual(result.returncode, 0, result.stdout)
        data = json.loads(result.stdout)
        phase4 = next(
            phase for phase in data["phases"] if phase["phase"] == "Phase 4 WHEP proxy"
        )
        evidence = "\n".join(phase4["evidence"])
        self.assertEqual(phase4["status"], "blocked")
        self.assertIn("live WHEP soak failed", evidence)
        self.assertIn(
            "Frigate strict FPS failed for north_driveway "
            "(camera_fps=10.1, process_fps=9.6, skipped_fps=0.2)",
            evidence,
        )
        self.assertIn(
            "current Frigate stats recovered cleanly for north_driveway",
            evidence,
        )
        self.assertIn(
            "2 Scrypted RTSP input ffprobe path(s) returned code 0",
            evidence,
        )
        self.assertIn(
            "Scrypted RTSP playback was accepted after the skipped-FPS blip",
            evidence,
        )

    def test_phase4_soak_whep_stream_failure_marks_live_soak_failed(self):
        root = self.make_root()
        proof_dir = root / "tmp"
        (proof_dir / "phase4_whep_soak_pre_recovery_20260518_174012.txt").unlink()
        (proof_dir / "phase4_whep_soak_20260519_180043.txt").write_text(
            "\n".join(
                [
                    'health={"mtx_alive": true, "wyze_authed": true, "active_streams": 5}',
                    '{"stream":"deck-sub","whep_reachable":true,"whep_status":200,"upstream_state":"new","video_ready":false,"audio_ready":false,"audio_packets_seen":0,"has_ever_had_media":true,"mediamtx_reachable":true,"mediamtx_status":200}',
                    "FAIL: deck-sub WHEP proxy must be reachable with video_ready=true and has_ever_had_media=true",
                    "FAIL: deck-sub WHEP upstream_state must not stay new",
                    "south_driveway\t10.0\t10.0\t0.0",
                    "north_driveway\t10.0\t10.0\t0.0",
                    "doorbell\t10.1\t10.1\t0.0",
                    "",
                    "## Sample 17 elapsed=484s",
                    '{"stream":"deck-sub","whep_reachable":true,"whep_status":200,"upstream_state":"connected","video_ready":true,"audio_ready":true,"audio_packets_seen":460,"has_ever_had_media":true,"mediamtx_reachable":true,"mediamtx_status":200}',
                ]
            ),
            encoding="utf-8",
        )

        result = subprocess.run(
            [str(STATUS), "--root", str(root), "--json"],
            cwd=ROOT,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False,
        )

        self.assertEqual(result.returncode, 0, result.stdout)
        data = json.loads(result.stdout)
        phase4 = next(
            phase for phase in data["phases"] if phase["phase"] == "Phase 4 WHEP proxy"
        )
        evidence = "\n".join(phase4["evidence"])
        self.assertEqual(phase4["status"], "blocked")
        self.assertIn("live WHEP soak failed", evidence)
        self.assertIn(
            "deck-sub WHEP proxy must be reachable with video_ready=true",
            evidence,
        )
        self.assertIn("deck-sub WHEP upstream_state must not stay new", evidence)

    def test_phase4_soak_endpoint_outage_marks_live_soak_failed(self):
        root = self.make_root()
        proof_dir = root / "tmp"
        (proof_dir / "phase4_whep_soak_pre_recovery_20260518_174012.txt").unlink()
        (proof_dir / "phase4_whep_soak_20260520_020822.txt").write_text(
            "\n".join(
                [
                    "## Sample 101 elapsed=3086s",
                    'health={"mtx_alive": true, "wyze_authed": true, "active_streams": 5}',
                    '{"stream":"deck-sub","whep_reachable":true,"whep_status":200,"upstream_state":"connected","video_ready":true,"audio_ready":true,"audio_packets_seen":82614,"has_ever_had_media":true,"mediamtx_reachable":true,"mediamtx_status":200}',
                    "south_driveway\t10.1\t10.1\t0.0",
                    "north_driveway\t10.1\t10.1\t0.0",
                    "doorbell\t10.0\t10.0\t0.0",
                    "",
                    "## Sample 102 elapsed=3117s",
                    "health=<empty>",
                    "FAIL: production /health did not respond",
                    "FAIL: back-yard-sub health/details did not respond",
                    "FAIL: deck-sub health/details did not respond",
                    "FAIL: Frigate stats did not respond",
                ]
            ),
            encoding="utf-8",
        )

        result = subprocess.run(
            [str(STATUS), "--root", str(root), "--json"],
            cwd=ROOT,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False,
        )

        self.assertEqual(result.returncode, 0, result.stdout)
        data = json.loads(result.stdout)
        phase4 = next(
            phase for phase in data["phases"] if phase["phase"] == "Phase 4 WHEP proxy"
        )
        evidence = "\n".join(phase4["evidence"])
        self.assertEqual(phase4["status"], "blocked")
        self.assertIn("live WHEP soak failed", evidence)
        self.assertIn("production /health did not respond", evidence)
        self.assertIn("deck-sub health/details did not respond", evidence)
        self.assertIn("Frigate stats did not respond", evidence)

    def test_phase3_prod_failure_surfaces_exact_sd_only_blockers(self):
        root = self.make_root()
        proof_dir = root / "tmp"
        (proof_dir / "phase3_prod_sd_only_20260519_194654.txt").write_text(
            "\n".join(
                [
                    "sd_only_option=false",
                    '{"camera":"back-yard","status_code":"200","sd_only":null,"enabled_feeds":["sd"],"hd_supported":true,"hd_enabled":false}',
                    '{"camera":"hamster","status_code":"200","sd_only":null,"enabled_feeds":["hd"],"hd_supported":true,"hd_enabled":true}',
                    '{"camera":"north-yard","status_code":"200","sd_only":null,"enabled_feeds":["hd","sd"],"hd_supported":true,"hd_enabled":true}',
                    '{"details_status":"200","aliases":"back-yard-sd deck-sd hamster north-yard north-yard-sd","only_sd_aliases":false,"no_main_aliases":false}',
                    "FAIL: production Phase 3 SD_ONLY proof failed.",
                ]
            ),
            encoding="utf-8",
        )

        result = subprocess.run(
            [str(STATUS), "--root", str(root), "--json"],
            cwd=ROOT,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False,
        )

        self.assertEqual(result.returncode, 0, result.stdout)
        data = json.loads(result.stdout)
        phase3 = next(
            phase for phase in data["phases"] if phase["phase"] == "Phase 3 SD_ONLY model"
        )
        evidence = "\n".join(phase3["evidence"])
        self.assertEqual(phase3["status"], "blocked")
        self.assertIn("production Supervisor option SD_ONLY is not true", evidence)
        self.assertIn(
            "production stream-config sd_only is not true for back-yard, hamster, north-yard",
            evidence,
        )
        self.assertIn(
            "production cameras without exactly one enabled SD feed: hamster=['hd'], north-yard=['hd', 'sd']",
            evidence,
        )
        self.assertIn(
            "production still reports HD supported for back-yard, hamster, north-yard",
            evidence,
        )
        self.assertIn("production still has HD enabled for hamster, north-yard", evidence)
        self.assertIn(
            "production go2rtc still exposes non-SD aliases hamster, north-yard",
            evidence,
        )
        self.assertIn(
            "Production Supervisor option SD_ONLY must be true",
            phase3["remaining"],
        )
        self.assertIn(
            "production stream configs must report sd_only=true",
            phase3["remaining"],
        )
        self.assertIn(
            "each production camera must expose exactly one enabled SD feed",
            phase3["remaining"],
        )
        self.assertIn(
            "production go2rtc aliases must be SD-only",
            phase3["remaining"],
        )
        self.assertNotIn("Production upgrade-cycle/dead-branch-removal", phase3["remaining"])

    def test_phase4_remaining_does_not_claim_passed_wedge_is_missing(self):
        root = self.make_root()
        proof_dir = root / "tmp"
        (proof_dir / "phase4_whep_soak_pre_recovery_20260518_174012.txt").unlink()
        (proof_dir / "phase4_whep_soak_20260519_122635.txt").write_text(
            "\n".join(
                [
                    "south_driveway\t10.1\t10.0\t0.1",
                    "FAIL: Frigate cameras must have positive camera/process FPS and skipped_fps=0",
                    "FAIL: Phase 4 WHEP soak failed.",
                ]
            ),
            encoding="utf-8",
        )
        (proof_dir / "phase4_whep_wedge_injection_20260519_123000.txt").write_text(
            "PASS: Phase 4 WHEP wedge injection proof passed.",
            encoding="utf-8",
        )

        result = subprocess.run(
            [str(STATUS), "--root", str(root), "--json"],
            cwd=ROOT,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False,
        )

        self.assertEqual(result.returncode, 0, result.stdout)
        data = json.loads(result.stdout)
        phase4 = next(
            phase for phase in data["phases"] if phase["phase"] == "Phase 4 WHEP proxy"
        )
        self.assertEqual(phase4["status"], "blocked")
        self.assertIn("WHEP wedge injection proof passed", "\n".join(phase4["evidence"]))
        self.assertIn("1-hour WHEP live soak is still failing", phase4["remaining"])
        self.assertNotIn("wedge proof is still missing", phase4["remaining"])

    def test_phase4_short_soak_pass_does_not_complete_one_hour_gate(self):
        root = self.make_complete_root()
        proof_dir = root / "tmp"
        (proof_dir / "phase4_whep_soak_20260519_235959.txt").write_text(
            "\n".join(
                [
                    "duration_seconds=120",
                    "## Sample 5 elapsed=120s",
                    "PASS: Phase 4 WHEP soak passed for all named streams.",
                ]
            ),
            encoding="utf-8",
        )

        result = subprocess.run(
            [str(STATUS), "--root", str(root), "--json"],
            cwd=ROOT,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False,
        )

        self.assertEqual(result.returncode, 0, result.stdout)
        data = json.loads(result.stdout)
        self.assertEqual(data["overall"], "incomplete")
        phase4 = next(
            phase for phase in data["phases"] if phase["phase"] == "Phase 4 WHEP proxy"
        )
        self.assertEqual(phase4["status"], "partial")
        self.assertIn("live WHEP soak pass is too short (120s < 3600s)", "\n".join(phase4["evidence"]))
        self.assertIn("1-hour WHEP live soak proof is still missing", phase4["remaining"])

    def test_phase4_preflight_pass_is_context_not_completion(self):
        root = self.make_root()
        proof_dir = root / "tmp"
        (proof_dir / "phase4_whep_soak_pre_recovery_20260518_174012.txt").unlink()
        (proof_dir / "phase4_whep_soak_20260519_180043.txt").write_text(
            "\n".join(
                [
                    "FAIL: deck-sub WHEP proxy must be reachable with video_ready=true and has_ever_had_media=true",
                    "FAIL: deck-sub WHEP upstream_state must not stay new",
                    "FAIL: Phase 4 WHEP soak failed.",
                ]
            ),
            encoding="utf-8",
        )
        (proof_dir / "phase4_whep_preflight_20260520_020449.txt").write_text(
            "\n".join(
                [
                    "duration_seconds=1",
                    "## Sample 2 elapsed=2s",
                    "PASS: Phase 4 WHEP soak passed for all named streams.",
                ]
            ),
            encoding="utf-8",
        )

        result = subprocess.run(
            [str(STATUS), "--root", str(root), "--json"],
            cwd=ROOT,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False,
        )

        self.assertEqual(result.returncode, 0, result.stdout)
        data = json.loads(result.stdout)
        phase4 = next(
            phase for phase in data["phases"] if phase["phase"] == "Phase 4 WHEP proxy"
        )
        evidence = "\n".join(phase4["evidence"])
        self.assertEqual(phase4["status"], "blocked")
        self.assertIn("live WHEP soak failed", evidence)
        self.assertIn("short WHEP preflight passed (2s)", evidence)
        self.assertIn("1-hour WHEP live soak is still failing", phase4["remaining"])

    def test_full_future_proof_bundle_reports_complete_and_strict_passes(self):
        root = self.make_complete_root()

        result = subprocess.run(
            [str(STATUS), "--root", str(root), "--json", "--strict"],
            cwd=ROOT,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False,
        )

        self.assertEqual(result.returncode, 0, result.stdout)
        data = json.loads(result.stdout)
        self.assertEqual(data["overall"], "complete")
        phases = {phase["phase"]: phase["status"] for phase in data["phases"]}
        self.assertEqual(set(phases.values()), {"complete"})


if __name__ == "__main__":
    unittest.main()

#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass
class PhaseStatus:
    phase: str
    status: str
    evidence: list[str]
    remaining: str


@dataclass
class ProofArtifact:
    path: Path | None
    text: str


def read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return ""


def latest_artifact(root: Path, *patterns: str) -> ProofArtifact:
    paths: list[Path] = []
    for pattern in patterns:
        paths.extend((root / "tmp").glob(pattern))
    if not paths:
        return ProofArtifact(None, "")
    latest = max(paths, key=lambda path: (path.stat().st_mtime_ns, path.name))
    return ProofArtifact(latest, read_text(latest))


def has_pass(proof: ProofArtifact, marker: str) -> bool:
    return bool(proof.path and marker in proof.text)


def has_fail(proof: ProofArtifact, marker: str) -> bool:
    return bool(proof.path and marker in proof.text)


def ready_route_failure_evidence(proof: ProofArtifact) -> list[str]:
    """Return short clues that prove /api/ready is hitting the old catch-all route."""
    if not proof.text:
        return []

    clues: list[str] = []
    for line in proof.text.splitlines():
        if line.startswith("ready_camera_lookup_error_samples="):
            clues.append(line)
            break
    if "ready_marker=camera_lookup_fallback" in proof.text:
        clues.append("ready_marker=camera_lookup_fallback")
    if "/api/ready is falling through to camera lookup" in proof.text:
        clues.append("/api/ready falls through to camera lookup")
    return clues


def phase3_prod_failure_evidence(proof: ProofArtifact) -> list[str]:
    """Return short clues for the production SD_ONLY proof failure."""
    if not proof.path or not proof.text:
        return []

    clues: list[str] = []
    configs: list[dict] = []
    aliases: list[str] = []
    for line in proof.text.splitlines():
        stripped = line.strip()
        if "sd_only_option=false" in stripped:
            clues.append("production Supervisor option SD_ONLY is not true")
        if not stripped.startswith("{"):
            continue
        try:
            row = json.loads(stripped)
        except json.JSONDecodeError:
            continue
        if "camera" in row:
            configs.append(row)
        raw_aliases = row.get("aliases")
        if isinstance(raw_aliases, str):
            aliases = [alias for alias in raw_aliases.split() if alias]

    if configs:
        sd_only_missing = sorted(
            str(row["camera"]) for row in configs if row.get("sd_only") is not True
        )
        if sd_only_missing:
            clues.append(
                "production stream-config sd_only is not true for "
                + ", ".join(sd_only_missing)
            )

        wrong_feeds = []
        for row in configs:
            feeds = row.get("enabled_feeds")
            if feeds != ["sd"]:
                wrong_feeds.append(f"{row.get('camera')}={feeds}")
        if wrong_feeds:
            clues.append(
                "production cameras without exactly one enabled SD feed: "
                + ", ".join(wrong_feeds)
            )

        hd_supported = sorted(
            str(row["camera"]) for row in configs if row.get("hd_supported") is True
        )
        if hd_supported:
            clues.append("production still reports HD supported for " + ", ".join(hd_supported))

        hd_enabled = sorted(
            str(row["camera"]) for row in configs if row.get("hd_enabled") is True
        )
        if hd_enabled:
            clues.append("production still has HD enabled for " + ", ".join(hd_enabled))

    if aliases:
        non_sd_aliases = sorted(alias for alias in aliases if not alias.endswith("-sd"))
        if non_sd_aliases:
            clues.append(
                "production go2rtc still exposes non-SD aliases "
                + ", ".join(non_sd_aliases)
            )

    return clues


def north_yard_failure_evidence(*proofs: ProofArtifact) -> list[str]:
    """Return short, non-secret clues for the North Yard live snapshot blocker."""
    clues: list[str] = []
    for proof in proofs:
        if not proof.path or not proof.text:
            continue
        text = proof.text
        snapshot_timed_out = (
            "snapshot_attempt=1 code=000000" in text
            or "route=/snapshot/north-yard.jpg code=000000" in text
            or "route=/snapshot/north-yard.jpg code=000 " in text
        )
        img_hashes = {
            part.split("=", 1)[1]
            for line in text.splitlines()
            if line.startswith("img_attempt=")
            or line.startswith("route=/img/north-yard.jpg")
            or line.startswith("route=/snapshot/north-yard.jpg")
            for part in line.split()
            if (
                (part.startswith("sha=") and part != "sha=")
                or (part.startswith("sha256=") and part != "sha256=<none>")
            )
        }
        has_changing_bridge_snapshots = not snapshot_timed_out and len(img_hashes) > 1
        registry_is_go2rtc = '"source":"go2rtc:' in text or '"source": "go2rtc:' in text
        direct_go2rtc_probe_is_authoritative = not (
            has_changing_bridge_snapshots and registry_is_go2rtc
        )
        if (
            snapshot_timed_out
        ):
            clues.append(f"{proof.path}: north-yard forced snapshot timed out")
        if (
            "img_attempt=1 code=200" in text
            and "img_attempt=2 code=200" in text
        ) or text.count("route=/img/north-yard.jpg code=200") >= 2:
            if len(img_hashes) == 1:
                clues.append(f"{proof.path}: north-yard cached image hash did not change")
        if '"source": "wyze-api"' in text or '"source":"wyze-api"' in text:
            clues.append(f"{proof.path}: north-yard snapshot registry source is wyze-api")
        if direct_go2rtc_probe_is_authoritative:
            if (
                "url=http://127.0.0.1:11984/api/frame.jpeg?src=north-yard code=000000" in text
                or "url=http://127.0.0.1:11984/api/frame.jpeg?src=north-yard code=000" in text
            ):
                clues.append(f"{proof.path}: north-yard go2rtc main frame route returned no bytes")
            if (
                "url=http://127.0.0.1:11984/api/frame.jpeg?src=north-yard-sd code=000000" in text
                or "url=http://127.0.0.1:11984/api/frame.jpeg?src=north-yard-sd code=000" in text
            ):
                clues.append(f"{proof.path}: north-yard go2rtc SD frame route returned no bytes")
        if "go2rtc_lan_ip_overrides" in text:
            clues.append(f"{proof.path}: north-yard LAN override is configured")
        if "ip=192.168.1.183 ping=down" in text or "192.168.1.183\tunreachable" in text:
            clues.append(f"{proof.path}: configured north-yard IP 192.168.1.183 is unreachable")
        if "ip=192.168.1.183 ping=up" in text or "192.168.1.183\treachable" in text:
            clues.append(f"{proof.path}: configured/current north-yard IP 192.168.1.183 is reachable")
        if "ip=192.168.1.185 ping=down" in text or "192.168.1.185\tunreachable" in text:
            clues.append(f"{proof.path}: override north-yard IP 192.168.1.185 is unreachable")
        if "80:48:2c:31:c9:e7" in text.lower() or "80482c31c9e7" in text.lower():
            if "Neighbor Entries" in text and "neigh=<none>" in text:
                clues.append(f"{proof.path}: north-yard MAC was not found in HA neighbor table")
    return clues


def frigate_soak_failure_evidence(proof: ProofArtifact) -> list[str]:
    """Return short clues for the Frigate strict-FPS failure inside a WHEP soak."""
    if not proof.path or not proof.text:
        return []

    lines = proof.text.splitlines()
    clues: list[str] = []
    for index, line in enumerate(lines):
        if line.strip() != "Unhealthy Frigate cameras:":
            continue
        stats: dict[str, tuple[str, str, str]] = {}
        for prior in reversed(lines[:index]):
            if prior.startswith("## "):
                break
            parts = prior.split("\t")
            if len(parts) == 4 and parts[0] not in stats:
                stats[parts[0]] = (parts[1], parts[2], parts[3])

        unhealthy: list[str] = []
        for candidate in lines[index + 1 :]:
            stripped = candidate.strip()
            if not stripped or stripped.startswith("FAIL:") or stripped.startswith("## "):
                break
            unhealthy.append(stripped)

        for camera in dict.fromkeys(unhealthy):
            if camera in stats:
                camera_fps, process_fps, skipped_fps = stats[camera]
                clues.append(
                    f"{proof.path}: Frigate strict FPS failed for {camera} "
                    f"(camera_fps={camera_fps}, process_fps={process_fps}, skipped_fps={skipped_fps})"
                )
            else:
                clues.append(f"{proof.path}: Frigate strict FPS failed for {camera}")
    return clues


def whep_soak_failure_evidence(proof: ProofArtifact) -> list[str]:
    """Return short clues for WHEP stream failures inside a live soak."""
    if not proof.path or not proof.text:
        return []

    clues: list[str] = []
    for line in proof.text.splitlines():
        if not line.startswith("FAIL: "):
            continue
        message = line.removeprefix("FAIL: ")
        if (
            " WHEP proxy must be reachable with video_ready=true" in message
            or " WHEP upstream_state must not stay new" in message
            or " reports audio_ready=true without audio packets" in message
            or message == "production /health did not respond"
            or message.endswith(" health/details did not respond")
            or message == "Frigate stats did not respond"
        ):
            clues.append(f"{proof.path}: {message}")
    return list(dict.fromkeys(clues))


def whep_soak_duration_seconds(proof: ProofArtifact) -> int:
    """Return the intended/live elapsed duration recorded by a WHEP soak artifact."""
    if not proof.path or not proof.text:
        return 0

    duration = 0
    for line in proof.text.splitlines():
        if line.startswith("duration_seconds="):
            try:
                duration = max(duration, int(line.split("=", 1)[1].strip()))
            except ValueError:
                continue
        if " elapsed=" in line and line.endswith("s"):
            try:
                elapsed = line.rsplit(" elapsed=", 1)[1].removesuffix("s")
                duration = max(duration, int(elapsed))
            except ValueError:
                continue
    return duration


def frigate_input_diag_evidence(proof: ProofArtifact) -> list[str]:
    """Return short clues from a focused Frigate/Scrypted input diagnostic."""
    if not proof.path or not proof.text:
        return []

    cameras = "<unknown>"
    current_stats_clean = False
    return_code_zero_count = 0
    playback_accepted = False
    in_stats = False

    for line in proof.text.splitlines():
        if line.startswith("cameras="):
            cameras = line.split("=", 1)[1].strip() or cameras
        elif line == "## Current Frigate Stats":
            in_stats = True
        elif line.startswith("## ") and line != "## Current Frigate Stats":
            in_stats = False
        elif in_stats:
            parts = line.split("\t")
            if len(parts) >= 4:
                try:
                    camera_fps = float(parts[1])
                    process_fps = float(parts[2])
                    skipped_fps = float(parts[3])
                except ValueError:
                    continue
                if camera_fps > 0 and process_fps > 0 and skipped_fps == 0:
                    current_stats_clean = True
        if '"return_code":0' in line:
            return_code_zero_count += line.count('"return_code":0')
        if "response headers RTSP/1.0 200 OK" in line or line == "RTP-Info:" or line.startswith("RTP-Info:"):
            playback_accepted = True

    clues: list[str] = []
    if current_stats_clean:
        clues.append(f"{proof.path}: current Frigate stats recovered cleanly for {cameras}")
    if return_code_zero_count:
        clues.append(f"{proof.path}: {return_code_zero_count} Scrypted RTSP input ffprobe path(s) returned code 0")
    if playback_accepted:
        clues.append(f"{proof.path}: Scrypted RTSP playback was accepted after the skipped-FPS blip")
    return clues


RECOVERY_PASS_MARKER = (
    "PASS: production bridge is recovered enough to resume the remaining live Phase 4/5 gates."
)


def stale_pre_recovery_failure(root: Path, proof: ProofArtifact) -> bool:
    if not proof.path or "pre_recovery" not in proof.path.name:
        return False
    recovery = latest_artifact(root, "ha_prod_recovery_verify_*.txt")
    if not has_pass(recovery, RECOVERY_PASS_MARKER) or not recovery.path:
        return False
    return recovery.path.stat().st_mtime_ns > proof.path.stat().st_mtime_ns


def phase1(root: Path) -> PhaseStatus:
    aggregate_path = root / "tmp/phase1_snapshot_soak_dev_quiet_20260518_092953/aggregate.json"
    screenshot_path = (
        root
        / "tmp/phase1_snapshot_soak_dev_quiet_20260518_092953/phase1_soak_proof_screenshot.png"
    )
    prod_proof = latest_artifact(
        root,
        "phase1_prod_snapshot_soak_*.txt",
        "phase1_prod_snapshot_soak_*.md",
        "phase1_production_snapshot_soak_*.txt",
        "phase1_production_snapshot_soak_*.md",
    )
    north_yard_snapshot = latest_artifact(
        root,
        "north_yard_authed_snapshot_reprobe_*.txt",
        "north_yard_current_reprobe_*.txt",
        "north_yard_live_reprobe_*.txt",
        "north_yard_snapshot_reprobe_*.txt",
    )
    north_yard_lan = latest_artifact(root, "north_yard_lan_sweep_*.txt")
    evidence: list[str] = []
    status = "missing"
    dev_passed = False
    north_yard_clues: list[str] = []

    if aggregate_path.exists():
        data = json.loads(aggregate_path.read_text(encoding="utf-8"))
        samples = data.get("samples")
        all_ok = data.get("all_samples_ok") is True
        all_changed = data.get("all_cameras_changed") is True
        failures = sum(
            int(camera.get("failures", 0))
            for camera in (data.get("per_cam") or {}).values()
            if isinstance(camera, dict)
        )
        evidence.append(
            f"{aggregate_path}: samples={samples}, all_ok={all_ok}, all_changed={all_changed}, failures={failures}"
        )
        if samples and samples >= 60 and all_ok and all_changed and failures == 0:
            status = "green-dev"
            dev_passed = True

    if screenshot_path.exists():
        evidence.append(f"{screenshot_path}: browser screenshot exists")
    elif status == "green-dev":
        status = "partial"
        evidence.append(f"{screenshot_path}: missing browser screenshot")
        dev_passed = False

    if has_pass(prod_proof, "PASS: production Phase 1 snapshot soak passed."):
        evidence.append(f"{prod_proof.path}: production snapshot soak passed")
        if dev_passed:
            status = "complete"
    elif has_fail(prod_proof, "FAIL: production Phase 1 snapshot soak failed."):
        evidence.append(f"{prod_proof.path}: production snapshot soak failed")
        north_yard_proofs = [north_yard_snapshot]
        if "## LAN Reachability" not in north_yard_snapshot.text:
            north_yard_proofs.append(north_yard_lan)
        north_yard_clues = north_yard_failure_evidence(*north_yard_proofs)
        evidence.extend(north_yard_clues)
        status = "blocked"
    elif dev_passed:
        evidence.append("Production Phase 1 snapshot soak proof is missing")

    if status == "complete":
        remaining = "Complete."
    elif status == "blocked" and north_yard_clues:
        remaining_bits: list[str] = []
        if any("forced snapshot timed out" in clue for clue in north_yard_clues):
            remaining_bits.append("North Yard authenticated snapshot must stop timing out")
        if any("go2rtc main frame route returned no bytes" in clue for clue in north_yard_clues):
            remaining_bits.append("North Yard go2rtc main frame must return a non-empty JPEG")
        if any("go2rtc SD frame route returned no bytes" in clue for clue in north_yard_clues):
            remaining_bits.append("North Yard go2rtc SD frame must return a non-empty JPEG")
        if any("cached image hash did not change" in clue for clue in north_yard_clues):
            remaining_bits.append("North Yard cached image hash must change during the production soak")
        if any("snapshot registry source is wyze-api" in clue for clue in north_yard_clues):
            remaining_bits.append("North Yard snapshot source must move off stale Wyze API cache or prove freshness")
        if any("is unreachable" in clue for clue in north_yard_clues):
            remaining_bits.append("North Yard LAN override/reachability must match the current camera path")
        if any("192.168.1.183 is reachable" in clue for clue in north_yard_clues) and any(
            "192.168.1.185 is unreachable" in clue for clue in north_yard_clues
        ):
            remaining_bits.append(
                "stale North Yard LAN override must stop replacing the reachable helper/current IP"
            )
        remaining = "; ".join(dict.fromkeys(remaining_bits)) + "."
    else:
        remaining = "Production snapshot soak proof is still required."

    return PhaseStatus(
        "Phase 1 snapshot pipeline",
        status,
        evidence or ["No Phase 1 aggregate proof found"],
        remaining,
    )


def phase2(root: Path) -> PhaseStatus:
    proof_path = root / "tmp/phase2_startup_soak_proof_20260518.md"
    prod_soak = latest_artifact(root, "phase2_prod_startup_soak_*.txt")
    proof = read_text(proof_path)
    checks = [
        "`/api` non-200 samples: `0`",
        "`/api/ready` non-200 samples: `0`",
        "empty catalog samples: `0`",
        "`min_camera_count`: `6`",
        "`max_camera_count`: `6`",
    ]
    passed = proof and all(check in proof for check in checks)
    evidence = [
        f"{proof_path}: dev startup soak proof {'passes checks' if passed else 'missing/incomplete'}"
    ]
    prod_blocked = False
    prod_passed = False
    if prod_soak.path:
        if has_pass(prod_soak, "PASS: production Phase 2 startup/API soak passed."):
            evidence.append(f"{prod_soak.path}: production startup/API soak passed")
            prod_passed = True
        elif has_fail(prod_soak, "FAIL: production Phase 2 startup/API soak failed."):
            if stale_pre_recovery_failure(root, prod_soak):
                evidence.append(f"{prod_soak.path}: pre-recovery production startup/API soak failed")
            else:
                evidence.append(f"{prod_soak.path}: production startup/API soak failed")
                for clue in ready_route_failure_evidence(prod_soak):
                    evidence.append(f"{prod_soak.path}: {clue}")
                prod_blocked = True
        else:
            evidence.append(f"{prod_soak.path}: production startup/API soak exists but is inconclusive")
    elif passed:
        evidence.append("Production Phase 2 startup/API soak proof is missing")
    return PhaseStatus(
        "Phase 2 startup readiness",
        "blocked"
        if prod_blocked
        else ("complete" if passed and prod_passed else ("green-dev" if passed else "missing")),
        evidence,
        "Latest production startup/API soak still fails; inspect the latest phase2_prod_startup_soak artifact."
        if prod_blocked
        else "Production post-restart/API/log soak still requires a passing scripts/ha_phase2_prod_startup_soak.sh artifact."
        if not (passed and prod_passed)
        else "Complete.",
    )


def phase3(root: Path) -> PhaseStatus:
    proof_path = root / "tmp/phase3_sd_only_live_proof_20260518.md"
    prod_proof = latest_artifact(
        root,
        "phase3_prod_sd_only_*.txt",
        "phase3_prod_sd_only_*.md",
        "phase3_production_sd_only_*.txt",
        "phase3_production_sd_only_*.md",
    )
    dead_branch_proof = latest_artifact(
        root,
        "phase3_dead_branch_audit_*.txt",
        "phase3_dead_branch_audit_*.md",
    )
    proof = read_text(proof_path)
    checks = [
        "Phase 3 is green for the live Home Assistant dev lane.",
        '"all_sd_only": true',
        '"all_one_feed": true',
        '"no_hd_supported": true',
        '"no_hd_enabled": true',
        '"status_code": 409',
        '"only_sd_aliases": true',
        '"no_main_aliases": true',
    ]
    passed = proof and all(check in proof for check in checks)
    prod_passed = has_pass(prod_proof, "PASS: production Phase 3 SD_ONLY proof passed.")
    dead_branch_passed = has_pass(
        dead_branch_proof, "PASS: Phase 3 dead branch audit passed."
    )
    prod_failure_clues: list[str] = []
    evidence = [
        f"{proof_path}: SD_ONLY dev proof {'passes checks' if passed else 'missing/incomplete'}"
    ]
    if prod_passed:
        evidence.append(f"{prod_proof.path}: production SD_ONLY proof passed")
    elif has_fail(prod_proof, "FAIL: production Phase 3 SD_ONLY proof failed."):
        evidence.append(f"{prod_proof.path}: production SD_ONLY proof failed")
        prod_failure_clues = phase3_prod_failure_evidence(prod_proof)
        for clue in prod_failure_clues:
            evidence.append(f"{prod_proof.path}: {clue}")
    elif passed:
        evidence.append("Production Phase 3 SD_ONLY proof is missing")
    if dead_branch_passed:
        evidence.append(f"{dead_branch_proof.path}: dead branch audit passed")
    elif has_fail(dead_branch_proof, "FAIL: Phase 3 dead branch audit failed."):
        evidence.append(f"{dead_branch_proof.path}: dead branch audit failed")
    elif passed:
        evidence.append("Phase 3 dead branch audit proof is missing")
    status = "complete" if passed and prod_passed and dead_branch_passed else ("green-dev" if passed else "missing")
    if has_fail(prod_proof, "FAIL: production Phase 3 SD_ONLY proof failed.") or has_fail(
        dead_branch_proof, "FAIL: Phase 3 dead branch audit failed."
    ):
        status = "blocked"

    if status == "complete":
        remaining = "Complete."
    elif prod_failure_clues:
        remaining_bits: list[str] = []
        if any("Supervisor option SD_ONLY is not true" in clue for clue in prod_failure_clues):
            remaining_bits.append("Production Supervisor option SD_ONLY must be true")
        if any("stream-config sd_only is not true" in clue for clue in prod_failure_clues):
            remaining_bits.append("production stream configs must report sd_only=true")
        if any("without exactly one enabled SD feed" in clue for clue in prod_failure_clues):
            remaining_bits.append("each production camera must expose exactly one enabled SD feed")
        if any("still reports HD supported" in clue for clue in prod_failure_clues):
            remaining_bits.append("production must stop reporting HD support")
        if any("still has HD enabled" in clue for clue in prod_failure_clues):
            remaining_bits.append("production must stop enabling HD feeds")
        if any("non-SD aliases" in clue for clue in prod_failure_clues):
            remaining_bits.append("production go2rtc aliases must be SD-only")
        if not dead_branch_passed:
            remaining_bits.append("Phase 3 dead-branch audit must pass after production SD_ONLY is true")
        remaining = "; ".join(dict.fromkeys(remaining_bits)) + "."
    elif not prod_passed:
        remaining = "Production SD_ONLY proof is still required."
    elif not dead_branch_passed:
        remaining = "Phase 3 dead-branch audit proof is still required."
    else:
        remaining = "Production upgrade-cycle/dead-branch-removal work remains after production is stable."
    return PhaseStatus(
        "Phase 3 SD_ONLY model",
        status,
        evidence,
        remaining,
    )


def phase4(root: Path) -> PhaseStatus:
    audit = read_text(root / "tmp/master_goal_gate_audit_20260518.md")
    doctor = latest_artifact(root, "ha_bridge_doctor_*.txt")
    soak = latest_artifact(root, "phase4_whep_soak_*.txt")
    preflight = latest_artifact(root, "phase4_whep_preflight_*.txt")
    frigate_monitor = latest_artifact(root, "frigate_skipped_fps_monitor_*.txt")
    frigate_input_diag = latest_artifact(root, "frigate_input_diag_*.txt")
    wedge = latest_artifact(
        root,
        "phase4_whep_wedge_injection_*.txt",
        "phase4_whep_wedge_injection_*.md",
    )
    evidence = []
    go_passed = False
    if "go test ./whep_proxy/...: PASS" in audit or "run_master_local_gates: PASS" in audit:
        evidence.append("Root WHEP Go gate recorded as passing in master audit")
        go_passed = True
    if doctor.path and "Frigate FPS" in doctor.text:
        evidence.append(f"{doctor.path}: Frigate FPS section exists")
    soak_passed = False
    soak_failed = False
    if soak.path:
        if has_pass(soak, "PASS: Phase 4 WHEP soak passed for all named streams."):
            soak_duration = whep_soak_duration_seconds(soak)
            if soak_duration >= 3600:
                evidence.append(f"{soak.path}: one-hour live WHEP soak passed")
                soak_passed = True
            else:
                evidence.append(
                    f"{soak.path}: live WHEP soak pass is too short ({soak_duration}s < 3600s)"
                )
        elif has_fail(soak, "FAIL: Phase 4 WHEP soak failed.") or has_fail(
            soak, "FAIL: Frigate cameras must have positive camera/process FPS and skipped_fps=0"
        ) or has_fail(
            soak, "WHEP proxy must be reachable with video_ready=true"
        ) or has_fail(
            soak, "WHEP upstream_state must not stay new"
        ) or has_fail(
            soak, "reports audio_ready=true without audio packets"
        ) or has_fail(
            soak, "production /health did not respond"
        ) or has_fail(
            soak, "health/details did not respond"
        ) or has_fail(
            soak, "Frigate stats did not respond"
        ):
            if stale_pre_recovery_failure(root, soak):
                evidence.append(f"{soak.path}: pre-recovery live WHEP soak failed")
            else:
                evidence.append(f"{soak.path}: live WHEP soak failed")
                evidence.extend(whep_soak_failure_evidence(soak))
                evidence.extend(frigate_soak_failure_evidence(soak))
                soak_failed = True
        else:
            evidence.append(f"{soak.path}: live WHEP soak exists but is inconclusive")
    elif go_passed:
        evidence.append("Phase 4 one-hour live WHEP soak proof is missing")
    if preflight.path:
        if has_pass(preflight, "PASS: Phase 4 WHEP soak passed for all named streams."):
            preflight_duration = whep_soak_duration_seconds(preflight)
            evidence.append(
                f"{preflight.path}: short WHEP preflight passed ({preflight_duration}s)"
            )
        elif has_fail(preflight, "FAIL: Phase 4 WHEP soak failed."):
            evidence.append(f"{preflight.path}: short WHEP preflight failed")
    frigate_monitor_failed = has_fail(
        frigate_monitor, "FAIL: Frigate FPS had one or more strict-gate blips."
    )
    if frigate_monitor.path:
        if frigate_monitor_failed:
            evidence.append(f"{frigate_monitor.path}: Frigate strict FPS monitor failed")
        elif has_pass(
            frigate_monitor,
            "PASS: Frigate FPS stayed strict-green for monitor window.",
        ):
            evidence.append(f"{frigate_monitor.path}: Frigate strict FPS monitor passed")
    if soak_failed:
        evidence.extend(frigate_input_diag_evidence(frigate_input_diag))
    wedge_passed = has_pass(wedge, "PASS: Phase 4 WHEP wedge injection proof passed.")
    if wedge_passed:
        evidence.append(f"{wedge.path}: WHEP wedge injection proof passed")
    elif has_fail(wedge, "FAIL: Phase 4 WHEP wedge injection proof failed."):
        evidence.append(f"{wedge.path}: WHEP wedge injection proof failed")
    elif go_passed:
        evidence.append("Phase 4 injected WHEP wedge proof is missing")
    blocked = (
        soak_failed
    ) or (
        frigate_monitor_failed and not soak_passed
    ) or has_fail(wedge, "FAIL: Phase 4 WHEP wedge injection proof failed.")
    remaining: list[str] = []
    if not go_passed:
        remaining.append("Root WHEP Go gate proof is missing")
    if not soak_passed:
        if soak_failed or frigate_monitor_failed:
            remaining.append("1-hour WHEP live soak is still failing")
        else:
            remaining.append("1-hour WHEP live soak proof is still missing")
    if not wedge_passed:
        if has_fail(wedge, "FAIL: Phase 4 WHEP wedge injection proof failed."):
            remaining.append("injected live wedge proof is failing")
        else:
            remaining.append("injected live wedge proof is still missing")
    return PhaseStatus(
        "Phase 4 WHEP proxy",
        "blocked"
        if blocked
        else ("complete" if go_passed and soak_passed and wedge_passed else ("partial" if evidence else "missing")),
        evidence or ["No WHEP/local gate evidence found"],
        "; ".join(remaining) + "." if remaining else "Complete.",
    )


def phase5(root: Path) -> PhaseStatus:
    audit = read_text(root / "tmp/master_goal_gate_audit_20260518.md")
    recovery = latest_artifact(root, "ha_prod_recovery_verify_*.txt")
    overlay_verify = latest_artifact(root, "phase5_prod_overlay_api_verify_*.txt")
    evidence = []
    build_passed = False
    canonical_passed = False
    if "home_assistant: matches canonical app + overlay" in audit:
        evidence.append("Overlay build check recorded as passing")
        build_passed = True
    if "whep_proxy/` is now canonical" in audit:
        evidence.append("Canonical WHEP source recorded in audit")
        canonical_passed = True
    recovery_passed = False
    if recovery.path:
        if has_pass(
            recovery,
            RECOVERY_PASS_MARKER,
        ):
            evidence.append(f"{recovery.path}: production recovery verifier passed")
            recovery_passed = True
        elif has_fail(
            recovery,
            "FAIL: production bridge is not ready for the remaining live Phase 4/5 gates.",
        ):
            evidence.append(f"{recovery.path}: production recovery verifier failed")
        else:
            evidence.append(f"{recovery.path}: production recovery verifier exists but is inconclusive")
    elif build_passed:
        evidence.append("Production recovery verifier proof is missing")
    overlay_passed = False
    if overlay_verify.path:
        if has_pass(overlay_verify, "PASS: production Phase 5 overlay/API proof passed."):
            evidence.append(f"{overlay_verify.path}: production overlay/API verifier passed")
            overlay_passed = True
        elif has_fail(overlay_verify, "FAIL: production Phase 5 overlay/API proof failed."):
            evidence.append(f"{overlay_verify.path}: production overlay/API verifier failed")
            for clue in ready_route_failure_evidence(overlay_verify):
                evidence.append(f"{overlay_verify.path}: {clue}")
        else:
            evidence.append(f"{overlay_verify.path}: production overlay/API verifier exists but is inconclusive")
    elif build_passed:
        evidence.append("Production Phase 5 overlay/API verifier proof is missing")
    blocked = (
        has_fail(
            recovery,
            "FAIL: production bridge is not ready for the remaining live Phase 4/5 gates.",
        )
        or has_fail(overlay_verify, "FAIL: production Phase 5 overlay/API proof failed.")
    )
    complete = build_passed and canonical_passed and recovery_passed and overlay_passed
    if complete:
        remaining = "Complete."
    elif has_fail(overlay_verify, "FAIL: production Phase 5 overlay/API proof failed."):
        remaining = "Production overlay/API verifier is still failing; inspect the latest phase5_prod_overlay_api_verify artifact."
    elif recovery_passed:
        remaining = "Production recovery is green, but production overlay/API proof is still missing."
    else:
        remaining = "Production overlay-built rebuild/API proof is blocked until production recovery verifier passes."
    return PhaseStatus(
        "Phase 5 three-tree consolidation",
        "blocked" if blocked else ("complete" if complete else ("partial" if evidence else "missing")),
        evidence or ["No Phase 5 local overlay evidence found"],
        remaining,
    )


def blocker(root: Path) -> tuple[bool, list[str]]:
    blocker_path = root / "tmp/prod_mtx_58888_blocker_20260518.md"
    blocker_text = read_text(blocker_path)
    latest_doctor_artifact = latest_artifact(root, "ha_bridge_doctor_*.txt")
    latest_doctor = latest_doctor_artifact.path
    doctor_text = latest_doctor_artifact.text
    latest_recovery = latest_artifact(root, "ha_prod_recovery_verify_*.txt")
    if (
        latest_recovery.path
        and has_pass(latest_recovery, RECOVERY_PASS_MARKER)
        and (
            not latest_doctor
            or latest_recovery.path.stat().st_mtime_ns >= latest_doctor.stat().st_mtime_ns
        )
    ):
        return False, [f"latest recovery verifier output: {latest_recovery.path}"]
    doctor_has_health = '"mtx_alive":' in doctor_text or "## Production Health" in doctor_text
    evidence_text = doctor_text if latest_doctor and doctor_has_health else blocker_text
    hits = []
    health_failed = '"mtx_alive": false' in evidence_text
    bind_failed = (
        "listen tcp :58888: bind: address already in use" in evidence_text
    )
    if health_failed:
        hits.append("production health reports mtx_alive=false")
    if bind_failed:
        hits.append("MediaMTX logs show :58888 bind conflict")
    if latest_doctor:
        hits.append(f"latest doctor output: {latest_doctor}")
    return health_failed and bind_failed, hits


def collect(root: Path) -> dict:
    phases = [phase1(root), phase2(root), phase3(root), phase4(root), phase5(root)]
    is_blocked, blocker_evidence = blocker(root)
    all_complete = all(phase.status == "complete" for phase in phases)
    overall = "complete" if all_complete and not is_blocked else ("blocked" if is_blocked else "incomplete")
    return {
        "overall": overall,
        "blocker_evidence": blocker_evidence,
        "phases": [asdict(phase) for phase in phases],
    }


def print_markdown(status: dict) -> None:
    print(f"overall: {status['overall']}")
    if status["blocker_evidence"]:
        print("\nblocker:")
        for item in status["blocker_evidence"]:
            print(f"- {item}")
    print("\n| Phase | Status | Remaining |")
    print("| --- | --- | --- |")
    for phase in status["phases"]:
        print(f"| {phase['phase']} | {phase['status']} | {phase['remaining']} |")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Summarize local proof artifacts for .goal-master.md without touching live Home Assistant."
    )
    parser.add_argument("--root", default=".", help="Repository root to inspect")
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON")
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Exit non-zero unless every phase is fully complete and not blocked",
    )
    args = parser.parse_args()

    status = collect(Path(args.root).resolve())
    if args.json:
        print(json.dumps(status, indent=2))
    else:
        print_markdown(status)

    if args.strict and status["overall"] != "complete":
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

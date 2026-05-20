#!/bin/sh
set -eu

ROOT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$ROOT_DIR"

run_step() {
  label="$1"
  shift
  printf '\n## %s\n' "$label"
  "$@"
}

run_step "Shell syntax" sh -n \
  scripts/build.sh \
  scripts/deploy_ha_local_addon.sh \
  scripts/ha_bridge_diag.sh \
  scripts/ha_bridge_doctor.sh \
  scripts/ha_dev_build.sh \
  scripts/ha_frigate_input_diag.sh \
  scripts/ha_north_yard_live_probe.sh \
  scripts/ha_phase3_dead_branch_audit.sh \
  scripts/ha_phase3_prod_sd_only_probe.sh \
  scripts/ha_phase2_prod_startup_soak.sh \
  scripts/ha_phase4_whep_soak.sh \
  scripts/ha_phase5_prod_overlay_api_verify.sh \
  scripts/ha_ssh.sh \
  scripts/ha_prod_recovery_verify.sh \
  scripts/run_v4kvs_trial.sh

run_step "Overlay build check" ./scripts/build.sh --check

run_step "Phase 1 snapshot tests" \
  python3 -m pytest \
    tests/test_go2rtc_snapshot_and_diagnostics.py \
    tests/test_preview_validation.py \
    tests/test_thumbnail_404_logging.py \
    -v --tb=short --timeout=20

run_step "Phase 5 packaging and helper safety tests" \
  python3 -m pytest \
    tests/test_ha_addon_packaging.py \
    tests/test_ha_bridge_doctor.py \
    tests/test_ha_frigate_input_diag.py \
    tests/test_ha_north_yard_live_probe.py \
    tests/test_ha_phase3_dead_branch_audit.py \
    tests/test_ha_phase3_prod_sd_only_probe.py \
    tests/test_ha_phase2_prod_startup_soak.py \
    tests/test_ha_phase4_whep_soak.py \
    tests/test_ha_phase5_prod_overlay_api_verify.py \
    tests/test_ha_prod_recovery_verify.py \
    -q --tb=short --timeout=20

run_step "Phase 4 WHEP Go tests" go test ./whep_proxy/... -v -count=1

run_step "Master proof artifact status" python3 scripts/master_goal_status.py

run_step "Full Python suite" python3 -m pytest -q --tb=short --timeout=20

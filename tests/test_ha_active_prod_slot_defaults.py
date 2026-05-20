from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
ACTIVE_PROD_SLUG = "local_docker_wyze_bridge_v4"


def test_live_verifiers_default_to_active_local_production_slot():
    scripts = [
        ROOT / "scripts" / "ha_bridge_doctor.sh",
        ROOT / "scripts" / "ha_prod_recovery_verify.sh",
        ROOT / "scripts" / "ha_phase2_prod_startup_soak.sh",
        ROOT / "scripts" / "ha_phase4_whep_soak.sh",
        ROOT / "scripts" / "ha_phase5_prod_overlay_api_verify.sh",
    ]

    for script in scripts:
        text = script.read_text(encoding="utf-8")
        assert f'PROD_SLUG="${{HA_PROD_ADDON_SLUG:-{ACTIVE_PROD_SLUG}}}"' in text

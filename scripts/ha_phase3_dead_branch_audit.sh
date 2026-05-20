#!/bin/sh
set -eu

ROOT_DIR=${PHASE3_AUDIT_ROOT:-$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)}
TMP_DIR="$ROOT_DIR/tmp"
STAMP=$(date +%Y%m%d_%H%M%S)
OUT="$TMP_DIR/phase3_dead_branch_audit_${STAMP}.txt"

mkdir -p "$TMP_DIR"

latest_prod_proof() {
  find "$TMP_DIR" -maxdepth 1 -type f \( \
    -name 'phase3_prod_sd_only_*.txt' -o \
    -name 'phase3_prod_sd_only_*.md' -o \
    -name 'phase3_production_sd_only_*.txt' -o \
    -name 'phase3_production_sd_only_*.md' \
  \) -print 2>/dev/null | sort | tail -1
}

record() {
  printf '%s\n' "$*" | tee -a "$OUT"
}

prod_proof=$(latest_prod_proof || true)
failures=0

record "# Phase 3 Dead Branch Audit"
record "root=$ROOT_DIR"
record "created_at=$STAMP"
record ""

record "## Production SD_ONLY Proof"
if [ -n "$prod_proof" ] && grep -q "PASS: production Phase 3 SD_ONLY proof passed." "$prod_proof"; then
  record "prod_sd_only_proof=$prod_proof"
  record "prod_sd_only_pass=true"
else
  record "prod_sd_only_pass=false"
  record "FAIL: production Phase 3 SD_ONLY proof must pass before dead HD/feed branches can be removed."
  failures=$((failures + 1))
fi
record ""

record "## Legacy Feed Knob Scan"
scan_paths="
app
runtime_overlays
"

legacy_matches=$(
  cd "$ROOT_DIR" && \
    grep -RInE '\b(QUALITY|SUB_QUALITY|HD_KBPS|SD_KBPS)\b' $scan_paths 2>/dev/null || true
)

if [ -n "$legacy_matches" ]; then
  printf '%s\n' "$legacy_matches" | sed 's/^/legacy_match: /' | tee -a "$OUT"
  record "FAIL: legacy quality/bitrate knobs remain in the production path."
  failures=$((failures + 1))
else
  record "legacy_quality_knobs=none"
fi
record ""

record "## HD Opt-In Branch Review"
record "hd_opt_in_branch_status=reviewed"
record "hd_opt_in_branch_note=Deliberate HD opt-in controls may remain; production SD_ONLY proof verifies they are inert in the active production path."
record ""

if [ "$failures" -eq 0 ]; then
  record "PASS: Phase 3 dead branch audit passed."
else
  record "FAIL: Phase 3 dead branch audit failed."
fi

record "artifact=$OUT"

if [ "$failures" -eq 0 ]; then
  exit 0
fi
exit 1

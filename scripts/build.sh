#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
BUILD_DIR="$ROOT_DIR/.build/runtime"

usage() {
  cat <<'EOF'
Usage:
  scripts/build.sh <home_assistant|ha_live_addon> [output_dir]
  scripts/build.sh --check
  scripts/build.sh --apply <home_assistant|ha_live_addon>

Builds a Home Assistant runtime tree from the canonical app/ source plus a
small runtime_overlays/<target>/ overlay.
EOF
}

python_build() {
  python3 - "$ROOT_DIR" "$@" <<'PY'
from __future__ import annotations

import filecmp
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(sys.argv[1])
MODE = sys.argv[2]
TARGETS = {
    "home_assistant": ROOT / "home_assistant",
    "ha_live_addon": ROOT / ".ha_live_addon",
}
IGNORED_NAMES = {".DS_Store", "__pycache__"}
IGNORED_SUFFIXES = {".pyc", ".pyo"}
IGNORED_PREFIXES = ("options_payload",)


def ignored(rel: Path) -> bool:
    if any(part in IGNORED_NAMES for part in rel.parts):
        return True
    if rel.suffix in IGNORED_SUFFIXES:
        return True
    if rel.name.startswith(IGNORED_PREFIXES):
        return True
    if ".runtime" in rel.parts:
        return True
    return False


def copy_tree(src: Path, dest: Path) -> None:
    if not src.exists():
        raise SystemExit(f"Missing source tree: {src}")
    for path in src.rglob("*"):
        rel = path.relative_to(src)
        if ignored(rel):
            continue
        target = dest / rel
        if path.is_dir():
            target.mkdir(parents=True, exist_ok=True)
        elif path.is_file():
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, target)


def build(target: str, dest: Path) -> None:
    overlay = ROOT / "runtime_overlays" / target
    if target not in TARGETS:
        raise SystemExit(f"Unknown target: {target}")
    if dest.exists():
        shutil.rmtree(dest)
    dest.mkdir(parents=True)
    copy_tree(ROOT / "app", dest / "app")
    copy_tree(ROOT / "whep_proxy", dest / "whep_proxy")
    copy_tree(overlay, dest)


def file_set(base: Path) -> set[Path]:
    return {
        path.relative_to(base)
        for path in base.rglob("*")
        if path.is_file() and not ignored(path.relative_to(base))
    }


def compare(expected: Path, actual: Path) -> list[str]:
    problems: list[str] = []
    expected_files = file_set(expected)
    actual_files = file_set(actual)
    for rel in sorted(expected_files - actual_files):
        problems.append(f"missing in actual: {rel}")
    for rel in sorted(actual_files - expected_files):
        problems.append(f"extra in actual: {rel}")
    for rel in sorted(expected_files & actual_files):
        if not filecmp.cmp(expected / rel, actual / rel, shallow=False):
            problems.append(f"content differs: {rel}")
    return problems


if MODE == "build":
    target = sys.argv[3]
    dest = Path(sys.argv[4])
    build(target, dest)
elif MODE == "apply":
    target = sys.argv[3]
    actual = TARGETS[target]
    with tempfile.TemporaryDirectory(prefix=f"wyze-build-{target}-") as tmp:
        generated = Path(tmp) / actual.name
        build(target, generated)
        if actual.exists():
            shutil.rmtree(actual)
        shutil.copytree(generated, actual)
elif MODE == "check":
    failed = False
    with tempfile.TemporaryDirectory(prefix="wyze-build-check-") as tmp:
        tmp_root = Path(tmp)
        for target, actual in TARGETS.items():
            generated = tmp_root / actual.name
            build(target, generated)
            problems = compare(generated, actual)
            if problems:
                failed = True
                print(f"{target}: drift detected")
                for problem in problems[:80]:
                    print(f"  - {problem}")
                if len(problems) > 80:
                    print(f"  - ... {len(problems) - 80} more")
            else:
                print(f"{target}: matches canonical app + overlay")
    raise SystemExit(1 if failed else 0)
else:
    raise SystemExit(f"Unknown mode: {MODE}")
PY
}

if [ "$#" -eq 0 ]; then
  usage >&2
  exit 1
fi

case "$1" in
  --check)
    [ "$#" -eq 1 ] || { usage >&2; exit 1; }
    python_build check
    ;;
  --apply)
    [ "$#" -eq 2 ] || { usage >&2; exit 1; }
    python_build apply "$2"
    ;;
  -h|--help|help)
    usage
    ;;
  home_assistant|ha_live_addon)
    target="$1"
    output="${2:-$BUILD_DIR/$target}"
    python_build build "$target" "$output"
    printf '%s\n' "Built $target at $output"
    ;;
  *)
    usage >&2
    exit 1
    ;;
esac

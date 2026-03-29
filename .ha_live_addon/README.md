# Docker Wyze Bridge (Dev Build)

This local Home Assistant add-on is the staging lane for this repository. It exists so we can validate changes over SSH before mirroring approved fixes into the production add-on and eventual PRs.

## What This Is For

- Baseline-checking the local Home Assistant add-on against the current production release line.
- Testing in-progress fixes before promoting them to the tracked production source tree.
- Running controlled prod/dev swap tests where production is stopped, the dev add-on is started, and production is restored when verification is done.

## Operating Rules

1. Install this add-on alongside the production **Docker Wyze Bridge** add-on.
2. Copy production settings into this dev add-on before the first test run.
3. Prefer running only one add-on at a time during validation windows, even though the dev build now uses its own host-network port block.
4. Stop production before starting the dev add-on when you need exact parity checks against production behavior.
5. Restore production after every test window.

## Baseline

- Add-on name: `Docker Wyze Bridge (Dev Build)`
- Add-on slug: `docker_wyze_bridge_dev`
- Baseline version: `4.2.0`

## Where The Real Instructions Live

The detailed local-only runbooks for setup, swapping, smoke checks, troubleshooting, and promotion live under `docs/maintainer/` in this workspace. Those docs are intentionally gitignored and are not part of the public repository.

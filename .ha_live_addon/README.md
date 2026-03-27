# Docker Wyze Bridge (Dev Build)

This local Home Assistant add-on is the staging lane for this repository. It exists so we can validate changes over SSH before mirroring approved fixes into the production add-on and eventual PRs.

## What This Is For

- Baseline-checking the local Home Assistant add-on against `4.0.2`.
- Testing in-progress fixes before promoting them to the tracked production source tree.
- Running controlled prod/dev swap tests where production is stopped, the dev add-on is started, and production is restored when verification is done.

## Operating Rules

1. Install this add-on alongside the production **Docker Wyze Bridge V4.0.2** add-on.
2. Copy production settings into this dev add-on before the first test run.
3. Never run production and dev at the same time because they intentionally share the same ports.
4. Stop production before starting the dev add-on.
5. Restore production after every test window.

## Baseline

- Add-on name: `Docker Wyze Bridge (Dev Build)`
- Add-on slug: `docker_wyze_bridge_dev`
- Baseline version: `4.0.2`

## Where The Real Instructions Live

The detailed local-only runbooks for setup, swapping, smoke checks, troubleshooting, and promotion live under `docs/maintainer/` in this workspace. Those docs are intentionally gitignored and are not part of the public repository.

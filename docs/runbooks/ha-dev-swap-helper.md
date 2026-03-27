# Home Assistant Dev Swap Helper

`scripts/ha_dev_build.sh` is a small safety wrapper for live Home Assistant staging.

## What It Does

- Syncs the repository's `.ha_live_addon/` tree into the Home Assistant local add-on slot.
- Copies the current production Wyze Bridge options into the dev add-on.
- Stops one bridge before starting the other so prod and dev never compete for the same host-network ports.
- Waits for the active bridge `/health` endpoint before declaring the swap complete.
- Optionally stops and restarts Frigate around the bridge handoff so Frigate does not reconnect mid-swap.

## Why Use It

Use it when you need a reversible live test window on the Home Assistant box.

It is useful because it bakes in the two lessons that mattered most on this system:

- prod and dev share host-network ports, so they must never run together;
- quick manual swaps can leave MediaMTX in a bind-race if the old ports have not cleared yet.

It is not meant to be a full deployment framework. It is just the smallest repeatable bridge handoff helper that keeps the HA box safe.

## Main Commands

```sh
scripts/ha_dev_build.sh status
scripts/ha_dev_build.sh swap-to-dev
scripts/ha_dev_build.sh restore-prod
```

- `status`: show current prod/dev add-on state.
- `swap-to-dev`: sync, rebuild, stop production, start dev, then run a bridge `/health` smoke check.
- `restore-prod`: stop dev, restart production, then run the same `/health` smoke check.

## What It Does Not Try To Do

- It does not prove camera-specific playback is healthy.
- It does not replace `scripts/ha_bridge_diag.sh` for `whep_proxy` or MediaMTX diagnostics.
- It does not guarantee Frigate is fully settled before every UI request during startup.

For bridge internals, use `scripts/ha_bridge_diag.sh` after the swap.

## Recommended Live Workflow

1. `scripts/ha_dev_build.sh status`
2. `scripts/ha_dev_build.sh swap-to-dev`
3. `scripts/ha_bridge_diag.sh --target dev --stream dog-run`
4. Run the actual live investigation.
5. `scripts/ha_dev_build.sh restore-prod`

If you only need a one-off experiment, a manual stop/start sequence is still valid. The helper is mainly for repeatable, low-drama swaps.

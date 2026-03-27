#!/bin/sh
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
REPO_DIR=$(CDPATH= cd -- "$SCRIPT_DIR/.." && pwd)

usage() {
  cat <<'EOF'
Usage: scripts/deploy_ha_local_addon.sh [--target dev|prod] [--no-rebuild]

Deploys the Home Assistant add-on source to the remote HA box over SSH.

Defaults:
- target: `dev`
- rebuild: enabled

`dev` syncs the full `.ha_live_addon/` tree to the remote local add-on folder.
`prod` preserves the historical patch-only deploy path for the production add-on.

Requires:
- scripts/.ha_ssh.env
- scripts/ha_ssh.sh

Optional values in `scripts/.ha_ssh.env`:
- `HA_DEV_ADDON_ROOT` for the remote dev add-on source path
- `HA_DEV_ADDON_SLUG` for the Home Assistant dev add-on slug
- `HA_DEV_REMOTE_CONFIG_SLUG` to rewrite the synced add-on manifest slug for a pre-indexed local add-on slot
- `HA_PROD_ADDON_ROOT` for the remote production add-on source path
- `HA_PROD_ADDON_SLUG` for the Home Assistant production add-on slug
EOF
}

TARGET="dev"
REBUILD="true"

while [ "$#" -gt 0 ]; do
  case "$1" in
    --help)
      usage
      exit 0
      ;;
    --target)
      TARGET="${2:-}"
      shift 2
      ;;
    --no-rebuild)
      REBUILD="false"
      shift
      ;;
    *)
      usage >&2
      exit 1
      ;;
  esac
done

. "$SCRIPT_DIR/.ha_ssh.env"

ha_apps() {
  "$SCRIPT_DIR/ha_ssh.sh" ha apps "$@"
}

addon_field() {
  slug="$1"
  field="$2"
  info=$(ha_apps info "$slug" --raw-json)
  printf '%s' "$info" | python3 -c 'import json,sys; data=json.load(sys.stdin).get("data", {}); value=data.get(sys.argv[1], ""); print(value if value is not None else "")' "$field"
}

copy_file() {
  src="$1"
  dest="$2"
  "$SCRIPT_DIR/ha_ssh.sh" mkdir -p "$dest"
  KEY_PATH=$(eval printf '%s' "$HA_SSH_KEY")
  scp -P "$HA_SSH_PORT" -i "$KEY_PATH" "$REPO_DIR/$src" "$HA_SSH_TARGET:$dest/$(basename "$src")"
}

sync_dev_tree() {
  REMOTE_ROOT="${HA_DEV_ADDON_ROOT:-/addons/local/wyze_bridge_dev}"
  APP_SLUG="${HA_DEV_ADDON_SLUG:-docker_wyze_bridge_dev}"
  REMOTE_CONFIG_SLUG="${HA_DEV_REMOTE_CONFIG_SLUG:-}"
  "$SCRIPT_DIR/ha_ssh.sh" mkdir -p "$REMOTE_ROOT"
  COPYFILE_DISABLE=1 tar \
    --exclude='.DS_Store' \
    --exclude='._*' \
    -C "$REPO_DIR/.ha_live_addon" -cf - . \
    | "$SCRIPT_DIR/ha_ssh.sh" "mkdir -p '$REMOTE_ROOT' && tar -xf - -C '$REMOTE_ROOT'"
  if [ -n "$REMOTE_CONFIG_SLUG" ]; then
    "$SCRIPT_DIR/ha_ssh.sh" sh -s -- "$REMOTE_ROOT" "$REMOTE_CONFIG_SLUG" <<'EOF'
set -eu
remote_root="$1"
remote_slug="$2"
for manifest in "$remote_root/config.yaml" "$remote_root/config.yml"; do
  [ -f "$manifest" ] || continue
  sed -i "s/^slug:.*/slug: $remote_slug/" "$manifest"
done
EOF
  fi
}

sync_prod_patch() {
  REMOTE_ROOT="${HA_PROD_ADDON_ROOT:-/addons/local/wyze_bridge}"
  APP_SLUG="${HA_PROD_ADDON_SLUG:-docker_wyze_bridge_v4}"
  copy_file "app/templates/index.html" "$REMOTE_ROOT/app/templates"
  copy_file "app/templates/base.html" "$REMOTE_ROOT/app/templates"
  copy_file "app/static/site.js" "$REMOTE_ROOT/app/static"
  copy_file "app/static/site.css" "$REMOTE_ROOT/app/static"
  copy_file "app/.env" "$REMOTE_ROOT/app"
  copy_file "app/wyzecam/api_models.py" "$REMOTE_ROOT/app/wyzecam"
  copy_file "app/wyze_bridge.py" "$REMOTE_ROOT/app"
  copy_file "app/wyzebridge/mtx_server.py" "$REMOTE_ROOT/app/wyzebridge"
  copy_file "app/wyzebridge/wyze_api.py" "$REMOTE_ROOT/app/wyzebridge"
  copy_file "app/wyzebridge/web_ui.py" "$REMOTE_ROOT/app/wyzebridge"
  copy_file "app/wyzebridge/wyze_stream.py" "$REMOTE_ROOT/app/wyzebridge"
  copy_file "app/frontend.py" "$REMOTE_ROOT/app"
  copy_file ".ha_live_addon/whep_proxy/main.go" "$REMOTE_ROOT/whep_proxy"
}

case "$TARGET" in
  dev)
    sync_dev_tree
    ;;
  prod)
    PROD_REPOSITORY=$(addon_field "$APP_SLUG" repository 2>/dev/null || printf '')
    if [ "$PROD_REPOSITORY" != "local" ]; then
      cat >&2 <<EOF
Refusing prod source sync for $APP_SLUG.
The installed production add-on is built from repository '$PROD_REPOSITORY', not from $REMOTE_ROOT.
Syncing files into $REMOTE_ROOT will not change the running production image.
Use the dev add-on lane (scripts/ha_dev_build.sh swap-to-dev) for parity-safe live testing, or patch the actual repository source that Supervisor rebuilds.
EOF
      exit 1
    fi
    sync_prod_patch
    ;;
  *)
    echo "Unknown target: $TARGET" >&2
    exit 1
    ;;
esac

if [ "$REBUILD" = "false" ]; then
  printf '%s\n' "Deploy complete: $TARGET source synced to $REMOTE_ROOT."
  exit 0
fi

ha_apps rebuild "$APP_SLUG" --force
INGRESS_ENTRY=$(ha_apps info "$APP_SLUG" --raw-json | python3 -c 'import json,sys; root=json.load(sys.stdin); data=root.get("data", {}); sys.stdout.write(data.get("ingress_entry", ""))')
TARGET_URL=""
if [ -n "$INGRESS_ENTRY" ]; then
  TARGET_URL="http://172.30.32.1:8123${INGRESS_ENTRY%/}/static/site.js"
else
  TARGET_URL="http://172.30.32.1:5000/static/site.js"
fi

set +e
"$SCRIPT_DIR/ha_ssh.sh" curl -fsS "$TARGET_URL" | grep -q "copyToClipboard"
RET=$?
set -e
if [ $RET -ne 0 ]; then
  echo "Warning: could not verify site.js from $TARGET_URL (curl/grep exit $RET)." >&2
fi

printf '%s\n' "Deploy complete: $APP_SLUG rebuilt."

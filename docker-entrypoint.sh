#!/usr/bin/env sh
# Unified entrypoint: works standalone and as a Home Assistant add-on.
set -e

OPTIONS=/data/options.json

# When running as an HA add-on, translate options.json into env vars.
if [ -f "$OPTIONS" ]; then
  HBOX_DISABLE_AUTH="$(python3 -c "import json;print(str(json.load(open('$OPTIONS')).get('disable_auth', True)).lower())")"
  HBOX_ALLOW_REGISTRATION="$(python3 -c "import json;print(str(json.load(open('$OPTIONS')).get('allow_registration', False)).lower())")"
  export HBOX_DISABLE_AUTH HBOX_ALLOW_REGISTRATION
fi

# Sensible defaults.
: "${HBOX_DATA_DIR:=/data}"
: "${HBOX_DISABLE_AUTH:=false}"
: "${HBOX_SECRET_KEY:=$(head -c 32 /dev/urandom | base64)}"
: "${HBOX_PORT:=7745}"
export HBOX_DATA_DIR HBOX_DISABLE_AUTH HBOX_SECRET_KEY HBOX_PORT

mkdir -p "$HBOX_DATA_DIR"

# Best-effort Home Assistant discovery registration (no-op outside HA).
python3 /app/backend/ha_discovery.py || true

cd /app/backend
exec gunicorn -b "0.0.0.0:${HBOX_PORT}" -w 2 --timeout 120 "app:create_app()"

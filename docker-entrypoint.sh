#!/usr/bin/env sh
# Unified entrypoint: works standalone and as a Home Assistant add-on.
set -e

OPTIONS=/data/options.json

# When running as an HA add-on, translate options.json into env vars.
if [ -f "$OPTIONS" ]; then
  HBOX_DISABLE_AUTH="$(python3 -c "import json;print(str(json.load(open('$OPTIONS')).get('disable_auth', True)).lower())")"
  HBOX_ALLOW_REGISTRATION="$(python3 -c "import json;print(str(json.load(open('$OPTIONS')).get('allow_registration', False)).lower())")"
  HBOX_MCP_ENABLED="$(python3 -c "import json;print(str(json.load(open('$OPTIONS')).get('enable_mcp', True)).lower())")"
  export HBOX_DISABLE_AUTH HBOX_ALLOW_REGISTRATION HBOX_MCP_ENABLED
fi

# Sensible defaults.
: "${HBOX_DATA_DIR:=/data}"
: "${HBOX_DISABLE_AUTH:=false}"
: "${HBOX_SECRET_KEY:=$(head -c 32 /dev/urandom | base64)}"
: "${HBOX_PORT:=7745}"
: "${HBOX_MCP_ENABLED:=true}"
: "${HBOX_MCP_PORT:=7766}"
export HBOX_DATA_DIR HBOX_DISABLE_AUTH HBOX_SECRET_KEY HBOX_PORT HBOX_MCP_PORT

mkdir -p "$HBOX_DATA_DIR"

# Best-effort Home Assistant discovery registration (no-op outside HA).
python3 /app/backend/ha_discovery.py || true

cd /app/backend

# MCP server for Home Assistant — runs alongside the app in this same container,
# talking to the local API. Exposes an SSE endpoint on HBOX_MCP_PORT.
if [ "${HBOX_MCP_ENABLED}" = "true" ]; then
  HBOX_MCP_API="http://127.0.0.1:${HBOX_PORT}/api/v1" \
    python3 /app/backend/mcp_server.py &
  echo "HomeHoard MCP server started on :${HBOX_MCP_PORT}/sse"
fi

exec gunicorn -b "0.0.0.0:${HBOX_PORT}" -w 2 --timeout 120 "app:create_app()"

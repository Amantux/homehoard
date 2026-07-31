#!/usr/bin/env sh
# Unified entrypoint: works standalone and as a Home Assistant add-on.
set -e

OPTIONS=/data/options.json

# When running as an HA add-on, translate options.json into env vars.
if [ -f "$OPTIONS" ]; then
  HBOX_DISABLE_AUTH="$(python3 -c "import json;print(str(json.load(open('$OPTIONS')).get('disable_auth', True)).lower())")"
  HBOX_ALLOW_REGISTRATION="$(python3 -c "import json;print(str(json.load(open('$OPTIONS')).get('allow_registration', False)).lower())")"
  HBOX_MCP_ENABLED="$(python3 -c "import json;print(str(json.load(open('$OPTIONS')).get('enable_mcp', True)).lower())")"
  HBOX_MCP_EXPOSE_EXTERNAL="$(python3 -c "import json;print(str(json.load(open('$OPTIONS')).get('mcp_expose_external', False)).lower())")"
  HBOX_OLLAMA_SEARCH_KEY="$(python3 -c "import json;v=json.load(open('$OPTIONS')).get('ollama_search_key');print('' if v is None else v)")"
  HBOX_BARCODE_LOOKUP="$(python3 -c "import json;print(str(json.load(open('$OPTIONS')).get('barcode_lookup', False)).lower())")"
  HBOX_BARCODE_DB_KEY="$(python3 -c "import json;v=json.load(open('$OPTIONS')).get('barcode_db_key');print('' if v is None else v)")"
  HBOX_DATABASE_URL="$(python3 -c "import json;v=json.load(open('$OPTIONS')).get('database_url');print('' if v is None else v)")"
  HBOX_MIGRATE_FROM_SQLITE="$(python3 -c "import json;print(str(json.load(open('$OPTIONS')).get('migrate_from_sqlite', False)).lower())")"
  HBOX_USE_SHARED_POSTGRES="$(python3 -c "import json;print(str(json.load(open('$OPTIONS')).get('use_shared_postgres', False)).lower())")"
  HBOX_POSTGRES_PROVISION_TOKEN="$(python3 -c "import json;v=json.load(open('$OPTIONS')).get('postgres_provision_token');print('' if v is None else v)")"
  export HBOX_DISABLE_AUTH HBOX_ALLOW_REGISTRATION HBOX_MCP_ENABLED HBOX_MCP_EXPOSE_EXTERNAL HBOX_OLLAMA_SEARCH_KEY HBOX_BARCODE_LOOKUP HBOX_BARCODE_DB_KEY HBOX_DATABASE_URL HBOX_MIGRATE_FROM_SQLITE HBOX_USE_SHARED_POSTGRES HBOX_POSTGRES_PROVISION_TOKEN
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

# Drop privileges to the non-root 'app' user for the server processes. Setup
# above (reading /data/options.json, secret gen) runs as root; make the data
# dir owned by app, then exec the servers via gosu. If we're already non-root
# (e.g. some runtimes), RUN_AS is empty and we just run directly.
RUN_AS=""
if [ "$(id -u)" = "0" ]; then
  chown -R app:app "$HBOX_DATA_DIR" 2>/dev/null || true
  RUN_AS="gosu app"
fi

# Best-effort Home Assistant discovery registration (no-op outside HA).
python3 /app/backend/ha_discovery.py || true

cd /app/backend

# Shared PostgreSQL: when enabled, discover the add-on and provision our own
# database (writes the DSN to /data/.database_url, which the app reads). Runs
# before schema init so migrations target the right database. Best-effort — it
# self-selects SQLite if anything is missing, so it never blocks startup.
$RUN_AS python3 -m app.pg_provision \
  || echo "HomeHoard: shared-PostgreSQL provisioning skipped."

# Initialize / migrate the database ONCE, before starting workers. Otherwise
# each of gunicorn's workers races to run create_all()/_migrate() on a fresh DB
# and one crashes with "table already exists". After this, the per-worker
# create_all() is a safe no-op.
echo "Initializing database schema…"
$RUN_AS python3 -c "from app import create_app; create_app()"

# MCP server for Home Assistant — runs alongside the app in this same container,
# talking to the local API. Exposes an SSE endpoint on HBOX_MCP_PORT.
if [ "${HBOX_MCP_ENABLED}" = "true" ]; then
  # HBOX_WORKER_ENABLED=false: the sidecar builds create_app() only for DB-backed
  # key lookups — it must NOT start a second AI-job worker (the main app runs it).
  HBOX_MCP_API="http://127.0.0.1:${HBOX_PORT}/api/v1" HBOX_WORKER_ENABLED=false \
    $RUN_AS python3 /app/backend/mcp_server.py &
  echo "HomeHoard MCP server started on :${HBOX_MCP_PORT}/sse"
fi

exec $RUN_AS gunicorn -b "0.0.0.0:${HBOX_PORT}" -w 2 --timeout 120 "app:create_app()"

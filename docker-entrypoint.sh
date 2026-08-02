#!/usr/bin/env sh
# Unified entrypoint: works standalone and as a Home Assistant add-on.
set -e

# options.json is deliberately NOT parsed here. The application reads it via one
# tested adapter (app.settings.load_ha_options), so the shell and Python cannot
# disagree about what the configuration is. Eleven separate `python3 -c`
# invocations used to re-parse the same file and duplicate its defaults — and
# they had already drifted: the shell defaulted disable_auth to TRUE while
# Config defaulted it to FALSE.

# The data dir is the one value the shell needs BEFORE Python can run (mkdir +
# chown happen as root, before the privilege drop). Everything else — port, MCP
# settings, auth — is resolved from the registry further down, so there is no
# second set of defaults here to drift from the declared ones.
: "${HBOX_DATA_DIR:=/data}"
# NOTE: HBOX_SECRET_KEY is intentionally NOT defaulted here. It used to be
# `head -c 32 /dev/urandom`, which minted a NEW signing key on every container
# start — silently logging every user out and voiding every issued API token
# (including MCP keys) on each restart. The application now generates one once
# and persists it under HBOX_DATA_DIR instead.
export HBOX_DATA_DIR

mkdir -p "$HBOX_DATA_DIR"

# Drop privileges to the non-root 'app' user for the server processes. The
# mkdir/chown above run as root; make the data dir owned by app, then run every
# long-lived process (including config resolution) via gosu. If we're already non-root
# (e.g. some runtimes), RUN_AS is empty and we just run directly.
RUN_AS=""
if [ "$(id -u)" = "0" ]; then
  # A root-owned /data from a previous release is fixed here (root can always
  # chown). The failure case is a read-only or non-chownable mount (ro bind,
  # some SMB/NFS-backed setups): the chown no-ops, we drop to uid 1000, and the
  # first request dies with "unable to open database file" hours later with no
  # explanation. So verify writability AS the app user and fail loudly now.
  chown -R app:app "$HBOX_DATA_DIR" 2>/dev/null || true
  if ! gosu app test -w "$HBOX_DATA_DIR"; then
    echo "HomeHoard: $HBOX_DATA_DIR is not writable by the 'app' user (uid 1000)." >&2
    echo "           The data directory must be writable by the container's app user." >&2
    exit 1
  fi
  RUN_AS="gosu app"
fi

cd /app/backend

# Validate the configuration before anything starts, so a bad options.json or
# env var fails immediately with EVERY problem listed, rather than booting into
# a confusing 500 on some later request.
if ! $RUN_AS python3 -m app.config_check; then
  echo "HomeHoard: refusing to start with invalid configuration (see above)." >&2
  exit 1
fi

# Read back the handful of values the shell itself needs, from the SAME source
# of truth the app uses. One process, one parse. Only structural values go
# through this eval; a secret must never be eval'd.
#
# Two guards on the eval itself: the output is filtered to RESOLVED_* lines, so
# a stray print() on any import path cannot become shell code; and the result is
# captured first and checked, because `eval "$(cmd)"` swallows cmd's exit
# status — a failed resolve would otherwise leave RESOLVED_PORT unset and
# gunicorn would bind to "0.0.0.0:".
#
# Written as `python3 -c '...'` rather than a heredoc inside $( ):
# the container's /bin/sh is dash, which failed to parse the heredoc form
# with a trailing pipe. `sh -n` on a bash-as-sh host accepts it, so only a
# real container run catches this.
RESOLVED=$($RUN_AS python3 -c 'from app.settings import load_settings
s = load_settings()
print(f"RESOLVED_PORT={s.PORT}")
print("RESOLVED_MCP_ENABLED=" + ("true" if s.MCP_ENABLED else "false"))
print(f"RESOLVED_MCP_PORT={s.MCP_PORT}")
print(f"RESOLVED_LOGLEVEL={s.LOG_LEVEL.lower()}")' | grep "^RESOLVED_[A-Z_]*=")
eval "$RESOLVED"
if [ -z "${RESOLVED_PORT:-}" ] || [ -z "${RESOLVED_MCP_PORT:-}" ]; then
  echo "HomeHoard: could not resolve settings for startup; refusing to start." >&2
  exit 1
fi

# Shared PostgreSQL: when enabled, discover the add-on and provision our own
# database (writes the DSN to /data/.database_url, which the app reads). Runs
# before schema init so migrations target the right database. Best-effort — it
# self-selects SQLite if anything is missing, so it never blocks startup.
# pg_provision logs its own reason on every fall-back-to-SQLite path and exits 0,
# so this `||` fires only when the module crashed — say that, rather than
# "skipped", which reads as a normal outcome.
$RUN_AS python3 -m app.pg_provision \
  || echo "HomeHoard: pg_provision failed unexpectedly; continuing on SQLite." >&2

# Initialize / migrate the database ONCE, before starting workers. Otherwise
# each of gunicorn's workers races to run create_all()/_migrate() on a fresh DB
# and one crashes with "table already exists". After this, the per-worker
# create_all() is a safe no-op.
echo "Initializing database schema…"
# Also report which backend the app actually booted against. Every "why is my
# data missing / why didn't the migration take" question starts here. /status
# and /diagnostics report it too, but the log is what an operator pastes into an
# issue — and it is the only one available if the app fails to serve at all.
$RUN_AS python3 -c "from app import create_app
app = create_app()
uri = app.config['SQLALCHEMY_DATABASE_URI']
print('HomeHoard: database backend =', 'sqlite' if uri.startswith('sqlite') else 'postgresql')"

# Best-effort Home Assistant discovery. Runs AFTER schema init and as the app
# user, matching the sibling add-ons: anything discovery needs to read (data
# dir, future minted credentials) must already exist and be owned by `app`.
# Failure is logged, not silenced with `|| true`: discovery is a convenience,
# but a silent failure is a mystery.
#
# ha_discovery.py returns 0 on EVERY path and prints its own reason (no token /
# registered / failed non-fatally), so this branch fires only if the script
# itself crashed. It used to claim "not running under Supervisor", which is the
# one thing that cannot be true here — that case exits 0 with its own message.
$RUN_AS python3 ha_discovery.py \
  || echo "HomeHoard: ha_discovery.py failed to run; HA discovery not attempted." >&2

# ---------------------------------------------------------------------------
# MCP server. Previously backgrounded and then orphaned by `exec gunicorn`, so a
# crashed MCP was invisible and SIGTERM never reached it. We now keep a
# supervising shell that forwards signals and reports an MCP exit.
# ---------------------------------------------------------------------------
MCP_PID=""
if [ "${RESOLVED_MCP_ENABLED}" = "true" ]; then
  # HBOX_WORKER_ENABLED=false: the sidecar builds create_app() only for DB-backed
  # key lookups — it must NOT start a second AI-job worker (the main app runs it).
  # mcp_server.py resolves everything else (host, port, tokens, external
  # exposure) from the registry itself, so nothing is passed twice.
  HBOX_WORKER_ENABLED=false HBOX_PROC=mcp \
    $RUN_AS python3 mcp_server.py &
  MCP_PID=$!
  echo "HomeHoard: MCP server started (pid $MCP_PID) on :${RESOLVED_MCP_PORT}/sse"
fi

GUNICORN_PID=""
shutdown() {
  [ -n "$GUNICORN_PID" ] && kill -TERM "$GUNICORN_PID" 2>/dev/null || true
  [ -n "$MCP_PID" ] && kill -TERM "$MCP_PID" 2>/dev/null || true
  wait
  exit 0
}
trap shutdown TERM INT

# --access-logfile/--error-logfile to stdout: without them gunicorn logs no
# requests at all, so there was zero request-level visibility. --log-level comes
# from the same setting the app uses, so the two cannot disagree.
$RUN_AS gunicorn -b "0.0.0.0:${RESOLVED_PORT}" -w 2 --timeout 120 \
  --log-level "${RESOLVED_LOGLEVEL}" --access-logfile - --error-logfile - \
  "app:create_app()" &
GUNICORN_PID=$!
echo "HomeHoard: gunicorn on :${RESOLVED_PORT}"

# Supervise. A dead MCP is reported rather than silently absent; a dead gunicorn
# takes the container down with its real exit status.
while true; do
  if [ -n "$MCP_PID" ] && ! kill -0 "$MCP_PID" 2>/dev/null; then
    echo "HomeHoard: WARNING - MCP server (pid $MCP_PID) exited. Assist voice" \
         "control is unavailable; the web app is unaffected." >&2
    MCP_PID=""
  fi
  if ! kill -0 "$GUNICORN_PID" 2>/dev/null; then
    wait "$GUNICORN_PID"
    status=$?
    echo "HomeHoard: gunicorn exited with status $status; shutting down." >&2
    [ -n "$MCP_PID" ] && kill -TERM "$MCP_PID" 2>/dev/null || true
    exit "$status"
  fi
  sleep 5
done

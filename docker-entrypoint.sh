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
print("RESOLVED_DISABLE_AUTH=" + ("true" if s.DISABLE_AUTH else "false"))
print(f"RESOLVED_MCP_PORT={s.MCP_PORT}")
print(f"RESOLVED_LOGLEVEL={s.LOG_LEVEL.lower()}")' | grep "^RESOLVED_[A-Z_]*=")
eval "$RESOLVED"
if [ -z "${RESOLVED_PORT:-}" ] || [ -z "${RESOLVED_MCP_PORT:-}" ]; then
  echo "HomeHoard: could not resolve settings for startup; refusing to start." >&2
  exit 1
fi

# Early stop handling. PID 1 silently drops a signal it has no handler for, so
# until `trap shutdown` below is installed a `docker stop` during boot did
# nothing and ended in SIGKILL — possibly mid-migration. This trap only records
# the request: sh runs it after the current foreground step (e.g. schema init)
# finishes, so a migration is never interrupted; we then exit at the next
# checkpoint instead of starting servers. (config.yaml `timeout:` gives that
# step time to finish before the Supervisor escalates to SIGKILL.)
STOP_REQUESTED=0
trap 'STOP_REQUESTED=1' TERM INT

# Shared PostgreSQL: when enabled, discover the add-on and provision our own
# database (writes the DSN to /data/.database_url, which the app reads). Runs
# before schema init so migrations target the right database. Best-effort — it
# self-selects SQLite if anything is missing, so it never blocks startup.
# pg_provision logs its own reason on every fall-back-to-SQLite path and exits 0,
# so this `||` fires only when the module crashed — say that, rather than
# "skipped", which reads as a normal outcome.
$RUN_AS python3 -m app.pg_provision \
  || echo "HomeHoard: pg_provision failed unexpectedly; continuing on SQLite." >&2
[ "$STOP_REQUESTED" = 1 ] && { echo "HomeHoard: stop requested during startup; exiting after pg_provision"; exit 0; }

# Initialize / migrate the database ONCE, before starting workers. Otherwise
# each of gunicorn's workers races to run create_all()/_migrate() on a fresh DB
# and one crashes with "table already exists". After this, the per-worker
# create_all() is a safe no-op. Mint the stable integration API key in the SAME
# process (race-free — no second create_all) whenever a machine client needs
# it: under the HA Supervisor (the integration), or in hardened mode with the
# MCP server on (its outbound calls need a REST key).
MINT_TOKEN=false
if [ -n "${SUPERVISOR_TOKEN:-}" ]; then MINT_TOKEN=true; fi
if [ "${RESOLVED_DISABLE_AUTH}" != "true" ] && [ "${RESOLVED_MCP_ENABLED}" = "true" ]; then
  MINT_TOKEN=true
fi
echo "Initializing database schema…"
# Also report which backend the app actually booted against. Every "why is my
# data missing / why didn't the migration take" question starts here. /status
# and /diagnostics report it too, but the log is what an operator pastes into an
# issue — and it is the only one available if the app fails to serve at all.
$RUN_AS env MINT_TOKEN="$MINT_TOKEN" python3 -c "import os
from app import create_app
app = create_app()
uri = app.config['SQLALCHEMY_DATABASE_URI']
print('HomeHoard: database backend =', 'sqlite' if uri.startswith('sqlite') else 'postgresql')
if os.environ.get('MINT_TOKEN') == 'true':
    from app.integration_token import ensure_integration_token
    ensure_integration_token(app)"
[ "$STOP_REQUESTED" = 1 ] && { echo "HomeHoard: stop requested during startup; exiting after schema init"; exit 0; }

# Best-effort Home Assistant discovery. Runs AFTER schema init and as the app
# user, matching the sibling add-ons: anything discovery needs to read (data
# dir, future minted credentials) must already exist and be owned by `app`.
# Failure is logged, not silenced with `|| true`: discovery is a convenience,
# but a silent failure is a mystery.
#
# ha_discovery.py returns 0 on EVERY path and prints its own reason (no token /
# registered / failed non-fatally, each retry with its attempt number).
#
# Backgrounded: HA Core may not be up yet when the add-on boots, so the script
# retries with bounded backoff (~2 min per call) — that must not delay gunicorn.
# It is expected to exit, so the supervise loop below does NOT watch it;
# shutdown() only signals it in case it is still retrying. It is launched
# directly (gosu execs, so $! is the python process) rather than wrapped in a
# `( … || echo "failed to run" )` subshell: TERM to the subshell would not reach
# python. The only case that echo covered — the script itself crashing — still
# surfaces as a Python traceback on stderr in the add-on log.
$RUN_AS python3 ha_discovery.py &
DISCOVERY_PID=$!
if [ "$STOP_REQUESTED" = 1 ]; then
  echo "HomeHoard: stop requested during startup; exiting after discovery launch"
  kill -TERM "$DISCOVERY_PID" 2>/dev/null || true
  exit 0
fi

# ---------------------------------------------------------------------------
# MCP server. Previously backgrounded and then orphaned by `exec gunicorn`, so a
# crashed MCP was invisible and SIGTERM never reached it. We now keep a
# supervising shell that forwards signals and reports an MCP exit.
# ---------------------------------------------------------------------------
MCP_PID=""          # the supervise loop (a background subshell), not the server
# The loop writes the CURRENT server pid here and shutdown() (root) kills
# whatever pid it names, so it lives in root-owned /run, not world-writable /tmp
# where another user could plant a pid. /tmp only when we already run non-root.
MCP_CHILD_PIDFILE="/run/homehoard-mcp.pid"
[ -w /run ] || MCP_CHILD_PIDFILE="/tmp/homehoard-mcp.pid"

# Restart a crashed MCP server up to 5 times (backoff 1,2,4,8,16s), then give up
# without touching the REST API. Runs in the background; TERM (from shutdown())
# sets STOPPING=1, stops the current server and any pending backoff, and exits.
# MCP_BACKOFF_SLEEP shortens the real sleeps (tests only); the log keeps the
# nominal delay.
supervise_mcp() {
  STOPPING=0
  child="" nap="" attempt=0
  trap 'STOPPING=1; [ -n "$nap" ] && kill -TERM "$nap" 2>/dev/null
        [ -n "$child" ] && kill -TERM "$child" 2>/dev/null && { wait "$child" || true; }
        rm -f "$MCP_CHILD_PIDFILE"; exit 0' TERM INT
  while [ "$STOPPING" != 1 ]; do
    start_mcp &
    child=$!
    echo "$child" > "$MCP_CHILD_PIDFILE"
    echo "HomeHoard: MCP server started (pid $child) on :${RESOLVED_MCP_PORT}/sse"
    status=0
    wait "$child" || status=$?   # `|| ` keeps set -e from killing the loop
    child=""
    [ "$STOPPING" = 1 ] && break
    [ "$status" -eq 0 ] && break   # a clean exit is deliberate, not a crash
    if [ "$attempt" -ge 5 ]; then
      echo "HomeHoard: MCP server gave up after 5 restarts — the REST API keeps" \
           "running; check the log above" >&2
      break
    fi
    attempt=$((attempt + 1))
    delay=$((1 << (attempt - 1)))
    echo "HomeHoard: MCP server exited (status $status), restart $attempt/5 in ${delay}s" >&2
    sleep "${MCP_BACKOFF_SLEEP:-$delay}" &
    nap=$!
    wait "$nap" || true
    nap=""
  done
  rm -f "$MCP_CHILD_PIDFILE"
}

if [ "${RESOLVED_MCP_ENABLED}" = "true" ]; then
  # In hardened mode the MCP server's own outbound calls to the REST API need a
  # key — hand it the minted integration token (full scope). Open mode reaches
  # the API without one, so this stays blank there.
  MCP_API_TOKEN=""
  if [ "${RESOLVED_DISABLE_AUTH}" != "true" ] && [ -f "${HBOX_DATA_DIR}/.integration_token" ]; then
    MCP_API_TOKEN="$(cat "${HBOX_DATA_DIR}/.integration_token" 2>/dev/null || true)"
  fi
  # HBOX_WORKER_ENABLED=false: the sidecar builds create_app() only for DB-backed
  # key lookups — it must NOT start a second AI-job worker (the main app runs it).
  # mcp_server.py resolves everything else (host, port, external exposure) from
  # the registry itself, so nothing is passed twice.
  start_mcp() {
    HBOX_WORKER_ENABLED=false HBOX_MCP_API_TOKEN="$MCP_API_TOKEN" \
      exec $RUN_AS python3 mcp_server.py
  }
  supervise_mcp &
  MCP_PID=$!
fi

GUNICORN_PID=""
shutdown() {
  [ -n "$GUNICORN_PID" ] && kill -TERM "$GUNICORN_PID" 2>/dev/null || true
  # TERM the supervise loop first (its trap sets STOPPING=1 and stops the
  # server), then the server directly in case the loop was between steps.
  [ -n "$MCP_PID" ] && kill -TERM "$MCP_PID" 2>/dev/null || true
  [ -n "$MCP_PID" ] && [ -f "$MCP_CHILD_PIDFILE" ] && kill -TERM "$(cat "$MCP_CHILD_PIDFILE")" 2>/dev/null || true
  [ -n "$DISCOVERY_PID" ] && kill -TERM "$DISCOVERY_PID" 2>/dev/null || true
  wait
  exit 0
}
trap shutdown TERM INT
# A stop that arrived while the MCP supervisor was being launched only set the
# early flag; honour it now that shutdown() can reach the children.
[ "$STOP_REQUESTED" = 1 ] && shutdown

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
    echo "HomeHoard: WARNING - MCP supervisor (pid $MCP_PID) stopped. Assist voice" \
         "control is unavailable; the web app is unaffected." >&2
    MCP_PID=""
  fi
  if ! kill -0 "$GUNICORN_PID" 2>/dev/null; then
    # `|| status=$?`: under set -e a bare `wait` on a non-zero exit would end
    # the script right here and skip the MCP cleanup below.
    status=0
    wait "$GUNICORN_PID" || status=$?
    echo "HomeHoard: gunicorn exited with status $status; shutting down." >&2
    [ -n "$MCP_PID" ] && kill -TERM "$MCP_PID" 2>/dev/null || true
    [ -n "$MCP_PID" ] && [ -f "$MCP_CHILD_PIDFILE" ] && kill -TERM "$(cat "$MCP_CHILD_PIDFILE")" 2>/dev/null || true
    exit "$status"
  fi
  # Backgrounded + wait so a TERM runs shutdown() at once instead of after the
  # sleep; `|| true` because a trap-interrupted wait returns >128 under set -e.
  sleep 5 & wait $! || true
done

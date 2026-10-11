"""Register HomeHoard with the Home Assistant Supervisor discovery service.

When running as a Home Assistant add-on, the Supervisor injects
``SUPERVISOR_TOKEN``. Posting to ``/discovery`` makes Home Assistant fire the
HomeHoard integration's ``async_step_hassio`` config flow, so the companion HACS
integration is offered for one-click setup ("New device found").

Safe to run outside HA — it no-ops when the token is absent.
"""
import json
import os
import socket
import sys
import time
import urllib.request

from app.settings import load_settings

SUPERVISOR_API = "http://supervisor"
TOKEN = os.environ.get("SUPERVISOR_TOKEN", "")
_SETTINGS = load_settings()
PORT = _SETTINGS.PORT
DATA_DIR = _SETTINGS.data_dir


def _retry(fn, what: str, attempts: int = 6, base: float = 2.0, cap: float = 60.0):
    """Call ``fn()`` until it succeeds, sleeping ``min(cap, base * 2**i)`` between tries.

    HA Core / the Supervisor may not be up yet when the add-on boots; six
    attempts span ~2 minutes (62 s of sleeps plus up to 10 s timeout per try).
    Every failure is printed with its attempt number and the last exception is
    re-raised so the caller decides how to degrade. ``time.sleep`` is looked up
    on the module so tests can patch it.
    """
    for i in range(attempts):
        try:
            return fn()
        except Exception as exc:  # noqa: BLE001 - best effort; caller degrades
            print(f"HomeHoard: {what} failed (attempt {i + 1}/{attempts}): {exc}")
            if i == attempts - 1:
                raise
            time.sleep(min(cap, base * 2 ** i))


def _integration_token() -> str:
    """Read the long-lived integration API key the app minted at startup.

    The app persists it to <data>/.integration_token (0600) before workers
    start; handing it to HA in the discovery payload authenticates the
    integration on the direct REST path. Best-effort: an empty string just
    means the integration falls back to the open path (unchanged behaviour)."""
    try:
        with open(os.path.join(DATA_DIR, ".integration_token"), encoding="utf-8") as fh:
            return fh.read().strip()
    except OSError:
        return ""


def _supervisor_self_info():
    """``/addons/self/info`` data, or None when the Supervisor can't be reached.

    Readable with the default ``hassio_role``; no ``manager`` needed for *self*.
    """
    if not TOKEN:
        return None
    req = urllib.request.Request(
        f"{SUPERVISOR_API}/addons/self/info",
        headers={"Authorization": f"Bearer {TOKEN}"},
    )

    def _get():
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read() or b"{}").get("data", {})

    try:
        return _retry(_get, "Supervisor self-info lookup")
    except Exception as exc:  # noqa: BLE001 - best effort; caller falls back
        print(f"HomeHoard: could not read add-on hostname from Supervisor ({exc}).")
        return None


def resolve_host():
    """The address HA Core should use to reach us, plus where it came from.

    The DNS name other containers resolve is the Supervisor-assigned add-on
    hostname (``local-<slug>`` / ``<repo>-<slug>``), which the Supervisor knows
    but the container itself does NOT. ``$HOSTNAME`` is this container's Docker
    id — it is not resolvable by HA Core, so a payload built from it points
    nowhere and zero-config setup silently fails. Ask the Supervisor.

    Precedence: explicit operator override -> Supervisor -> container hostname
    (last-resort, and only correct outside HA).
    """
    override = load_settings().DISCOVERY_HOST.strip()
    if override:
        return override, "HBOX_DISCOVERY_HOST"
    info = _supervisor_self_info() or {}
    hostname = (info.get("hostname") or "").strip()
    if hostname:
        return hostname, "supervisor"
    return (os.environ.get("HOSTNAME") or socket.gethostname()), "container-id (not resolvable by HA Core)"


def build_payload(host: str) -> dict:
    """The Supervisor discovery message the companion integration consumes."""
    return {"service": "homehoard",
            "config": {"host": host, "port": PORT, "token": _integration_token()}}


def _ready_probe() -> None:
    """Raise unless the local app answers /api/v1/ready with 2xx.

    PORT is the same resolved setting the entrypoint exports as RESOLVED_PORT
    and binds gunicorn to. urlopen raises HTTPError on the 503 'not ready'."""
    with urllib.request.urlopen(f"http://127.0.0.1:{PORT}/api/v1/ready", timeout=5):
        return None


def _wait_until_ready() -> bool:
    """Wait (~4 min: 10 tries, 2 s doubling, capped at 30 s) for the app to be
    ready, so HA isn't offered a setup whose first probe hits a dead port.
    Returns False if it never became ready; the caller posts anyway — a late
    offer beats none."""
    try:
        _retry(_ready_probe, "readiness wait", attempts=10, base=2.0, cap=30.0)
        return True
    except Exception:  # noqa: BLE001 - best effort; caller degrades
        return False


def main() -> int:
    if not TOKEN:
        print("SUPERVISOR_TOKEN not set — skipping HA discovery (fine outside HA).")
        return 0

    if not _wait_until_ready():
        print("HomeHoard: app never reported ready — registering discovery anyway.")

    host, source = resolve_host()
    message = build_payload(host)
    print(f"HomeHoard: advertising host {host!r} (source: {source}), "
          f"token {'set' if message['config']['token'] else 'absent'}.")
    payload = json.dumps(message).encode()

    req = urllib.request.Request(
        f"{SUPERVISOR_API}/discovery",
        data=payload,
        method="POST",
        headers={
            "Authorization": f"Bearer {TOKEN}",
            "Content-Type": "application/json",
        },
    )

    def _post():
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read() or b"{}")

    try:
        body = _retry(_post, "discovery registration")
        print("HomeHoard discovery registered:", body.get("data", {}).get("uuid"))
        return 0
    except Exception as exc:  # noqa: BLE001 - best effort, never block startup
        print(f"Discovery registration failed (non-fatal): {exc}")
        return 0


if __name__ == "__main__":
    sys.exit(main())

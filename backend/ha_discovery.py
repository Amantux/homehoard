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
import urllib.request

from app.settings import load_settings

SUPERVISOR_API = "http://supervisor"
TOKEN = os.environ.get("SUPERVISOR_TOKEN", "")
PORT = load_settings().PORT


def _supervisor_self_info():
    """``/addons/self/info`` data, or None when the Supervisor can't be reached.

    Readable with the default ``hassio_role``; no ``manager`` needed for *self*.
    """
    if not TOKEN:
        return None
    try:
        req = urllib.request.Request(
            f"{SUPERVISOR_API}/addons/self/info",
            headers={"Authorization": f"Bearer {TOKEN}"},
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read() or b"{}").get("data", {})
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
    return {"service": "homehoard", "config": {"host": host, "port": PORT}}


def main() -> int:
    if not TOKEN:
        print("SUPERVISOR_TOKEN not set — skipping HA discovery (fine outside HA).")
        return 0

    host, source = resolve_host()
    print(f"HomeHoard: advertising host {host!r} (source: {source}).")
    payload = json.dumps(build_payload(host)).encode()

    req = urllib.request.Request(
        f"{SUPERVISOR_API}/discovery",
        data=payload,
        method="POST",
        headers={
            "Authorization": f"Bearer {TOKEN}",
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            body = json.loads(resp.read() or b"{}")
            print("HomeHoard discovery registered:", body.get("data", {}).get("uuid"))
        return 0
    except Exception as exc:  # noqa: BLE001 - best effort, never block startup
        print(f"Discovery registration failed (non-fatal): {exc}")
        return 0


if __name__ == "__main__":
    sys.exit(main())

"""Register Shelfie with the Home Assistant Supervisor discovery service.

When running as a Home Assistant add-on, the Supervisor injects
``SUPERVISOR_TOKEN``. Posting to ``/discovery`` makes Home Assistant fire the
Shelfie integration's ``async_step_hassio`` config flow, so the companion HACS
integration is offered for one-click setup ("New device found").

Safe to run outside HA — it no-ops when the token is absent.
"""
import json
import os
import socket
import sys
import urllib.request

SUPERVISOR_API = "http://supervisor"
TOKEN = os.environ.get("SUPERVISOR_TOKEN", "")
PORT = int(os.environ.get("HBOX_PORT", "7745"))


def main() -> int:
    if not TOKEN:
        print("SUPERVISOR_TOKEN not set — skipping HA discovery (fine outside HA).")
        return 0

    # Other containers (HA core) reach an add-on by its container hostname.
    host = os.environ.get("HOSTNAME") or socket.gethostname()
    payload = json.dumps(
        {"service": "shelfie", "config": {"host": host, "port": PORT}}
    ).encode()

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
            print("Shelfie discovery registered:", body.get("data", {}).get("uuid"))
        return 0
    except Exception as exc:  # noqa: BLE001 - best effort, never block startup
        print(f"Discovery registration failed (non-fatal): {exc}")
        return 0


if __name__ == "__main__":
    sys.exit(main())

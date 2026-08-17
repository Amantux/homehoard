"""Provision a stable API key for the Home Assistant companion integration.

The HomeHoard integration polls the REST API directly (not via ingress), so it
must authenticate with a long-lived API key rather than rely on the open
fallback. We mint one at startup, bind it to the shared household, and persist
the RAW token to a private file in the data dir so that:

* it stays **stable across restarts** — re-minting each boot would invalidate the
  token the already-configured integration stored, breaking it; and
* the **discovery step** (``ha_discovery.py``, a separate process) can read it
  to hand Home Assistant the token in the discovery payload.

The raw token is a secret: the file is ``0600`` and its value is never logged.
Only a SHA-256 hash is stored in the DB (plus a short display ``hint``), so the
key is revocable in Settings → API keys like any other.
"""
from __future__ import annotations

import logging
import os

_LOGGER = logging.getLogger("homehoard.integration_token")

TOKEN_NAME = "Home Assistant integration"
_RAW_FILENAME = ".integration_token"


def _raw_path() -> str:
    # Single source of truth for the data dir is the resolved config (not env),
    # so tests and the running app never disagree about the file location.
    from flask import current_app

    return os.path.join(current_app.config["DATA_DIR"], _RAW_FILENAME)


def ensure_integration_token(app=None) -> str | None:
    """Return the raw integration token, creating it once and reusing it after.

    Pass ``app`` to run against an existing application (tests, startup);
    otherwise a fresh app is built. Best-effort: returns ``None`` (logged) if
    provisioning fails, so startup/discovery never blocks — the integration just
    falls back to the open path.
    """
    try:
        from .auth import _default_user
        from .extensions import db
        from .models import ApiToken, generate_raw_token, hash_token

        if app is None:
            from . import create_app

            app = create_app()
        with app.app_context():
            path = _raw_path()
            # Reuse a previously-minted token if the raw file still matches a live
            # DB record — keeps the integration's stored token valid across boots.
            if os.path.isfile(path):
                with open(path, encoding="utf-8") as fh:
                    raw = fh.read().strip()
                if raw and (
                    db.session.query(ApiToken)
                    .filter_by(token_hash=hash_token(raw))
                    .first()
                ):
                    return raw

            # Bind to the shared household (the earliest-created group, the one
            # ingress users are provisioned into) via the fixed _default_user, or
            # the integration would read a different, empty household.
            owner = _default_user()
            raw = generate_raw_token()
            record = ApiToken(
                name=TOKEN_NAME,
                token_hash=hash_token(raw),
                hint=raw[:9],
                scope="full",
                user_id=owner.id,
                group_id=owner.group_id,
            )
            db.session.add(record)
            db.session.commit()

            # Persist raw for restart-stability + discovery handoff (0600).
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(fd, "w") as fh:
                fh.write(raw)
            _LOGGER.info("Provisioned Home Assistant integration API key (%s…)", raw[:9])
            return raw
    except Exception as exc:  # noqa: BLE001 - best effort; never block startup
        _LOGGER.warning("Integration token provisioning failed (non-fatal): %s", exc)
        return None

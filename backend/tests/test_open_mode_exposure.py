"""Open mode (DISABLE_AUTH) warns when reached from off the HA network.

DISABLE_AUTH is only safe behind HA ingress. A request that falls through to the
shared default user from any other (non-loopback) peer means the port is
published — log that once per peer so the operator can see it.
"""
import logging

import pytest

from app import auth

MSG = "unauthenticated access from"


@pytest.fixture(autouse=True)
def _fresh_warned_set():
    auth._OPEN_MODE_WARNED.clear()
    yield
    auth._OPEN_MODE_WARNED.clear()


def _hits(caplog):
    return [r for r in caplog.records if MSG in r.getMessage()]


def _get(noauth_app, peer):
    client = noauth_app.test_client()
    return client.get("/api/v1/locations", environ_base={"REMOTE_ADDR": peer})


def test_off_network_peer_warns_once(noauth_app, caplog):
    caplog.set_level(logging.WARNING, logger="homehoard.auth")
    assert _get(noauth_app, "10.0.0.5").status_code == 200
    assert _get(noauth_app, "10.0.0.5").status_code == 200
    hits = _hits(caplog)
    assert len(hits) == 1
    assert "10.0.0.5" in hits[0].getMessage()


def test_ingress_peer_does_not_warn(noauth_app, caplog):
    caplog.set_level(logging.WARNING, logger="homehoard.auth")
    assert _get(noauth_app, "172.30.32.2").status_code == 200
    assert _hits(caplog) == []


def test_loopback_peer_does_not_warn(noauth_app, caplog):
    caplog.set_level(logging.WARNING, logger="homehoard.auth")
    assert _get(noauth_app, "127.0.0.1").status_code == 200
    assert _hits(caplog) == []


def test_warned_set_is_bounded(noauth_app, caplog, monkeypatch):
    caplog.set_level(logging.WARNING, logger="homehoard.auth")
    monkeypatch.setattr(auth, "_OPEN_MODE_WARNED_CAP", 1)
    _get(noauth_app, "10.0.0.5")
    _get(noauth_app, "10.0.0.6")
    assert len(auth._OPEN_MODE_WARNED) == 1
    assert len(_hits(caplog)) == 1

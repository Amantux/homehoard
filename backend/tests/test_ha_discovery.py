"""Supervisor discovery payload — what Home Assistant learns about this add-on.

The host is the load-bearing field: HA Core reaches an add-on by its
Supervisor-assigned DNS name (``local-<slug>``), NOT by ``$HOSTNAME``, which is
this container's Docker id and resolves nowhere. A payload built from the
container id looks fine in the log and silently breaks zero-config setup.

These drive the builders directly (no Supervisor, no network), which is the
whole reason they're separate from ``main()``.
"""
import ha_discovery


def test_host_comes_from_the_supervisor_not_the_container_id(monkeypatch):
    monkeypatch.setenv("HOSTNAME", "9f3c1b2d4e5a")  # a Docker container id
    monkeypatch.delenv("HBOX_DISCOVERY_HOST", raising=False)
    monkeypatch.setattr(
        ha_discovery, "_supervisor_self_info", lambda: {"hostname": "local-homehoard"})

    host, source = ha_discovery.resolve_host()

    assert host == "local-homehoard"
    assert source == "supervisor"
    assert ha_discovery.build_payload(host)["config"]["host"] == "local-homehoard"


def test_falls_back_to_the_container_hostname_when_supervisor_is_unreachable(monkeypatch):
    """Degrade, never crash: outside HA (or on a Supervisor hiccup) the old
    behaviour is still the best guess available."""
    monkeypatch.setenv("HOSTNAME", "9f3c1b2d4e5a")
    monkeypatch.delenv("HBOX_DISCOVERY_HOST", raising=False)
    monkeypatch.setattr(ha_discovery, "_supervisor_self_info", lambda: None)

    host, source = ha_discovery.resolve_host()

    assert host == "9f3c1b2d4e5a"
    assert "not resolvable" in source  # the log says why this is a last resort


def test_a_blank_supervisor_hostname_is_not_advertised(monkeypatch):
    """`hostname: ""` in the response must fall through, not publish an empty host."""
    monkeypatch.setenv("HOSTNAME", "9f3c1b2d4e5a")
    monkeypatch.delenv("HBOX_DISCOVERY_HOST", raising=False)
    monkeypatch.setattr(ha_discovery, "_supervisor_self_info", lambda: {"hostname": ""})

    host, _ = ha_discovery.resolve_host()

    assert host == "9f3c1b2d4e5a"


def test_an_explicit_operator_override_wins(monkeypatch):
    monkeypatch.setenv("HOSTNAME", "9f3c1b2d4e5a")
    monkeypatch.setenv("HBOX_DISCOVERY_HOST", "homehoard.lan")
    monkeypatch.setattr(
        ha_discovery, "_supervisor_self_info", lambda: {"hostname": "local-homehoard"})

    host, source = ha_discovery.resolve_host()

    assert host == "homehoard.lan"
    assert source == "HBOX_DISCOVERY_HOST"


def test_payload_shape_is_what_the_integration_reads():
    payload = ha_discovery.build_payload("local-homehoard")

    assert payload["service"] == "homehoard"
    assert payload["config"]["host"] == "local-homehoard"
    assert payload["config"]["port"] == ha_discovery.PORT


def test_supervisor_lookup_is_skipped_without_a_token(monkeypatch):
    """No token means we're not under the Supervisor — don't attempt the call."""
    monkeypatch.setattr(ha_discovery, "TOKEN", "")

    assert ha_discovery._supervisor_self_info() is None

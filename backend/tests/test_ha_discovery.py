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


def test_payload_carries_the_minted_integration_token(monkeypatch, tmp_path):
    monkeypatch.setattr(ha_discovery, "DATA_DIR", str(tmp_path))
    (tmp_path / ".integration_token").write_text("hh_abc123")

    payload = ha_discovery.build_payload("local-homehoard")

    assert payload["config"]["token"] == "hh_abc123"


def test_payload_token_is_blank_when_none_minted_yet(monkeypatch, tmp_path):
    monkeypatch.setattr(ha_discovery, "DATA_DIR", str(tmp_path))

    payload = ha_discovery.build_payload("local-homehoard")

    assert payload["config"]["token"] == ""


class _FakeResponse:
    def __init__(self, body: bytes):
        self._body = body

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _discovery_env(monkeypatch, outcomes):
    """Run main() under a fake Supervisor whose /discovery answers per ``outcomes``
    (an exception instance = that attempt fails). Returns (posts, sleeps)."""
    posts, sleeps = [], []
    remaining = list(outcomes)

    def fake_urlopen(req, timeout=None):
        assert req.full_url.endswith("/discovery")
        posts.append(req)
        outcome = remaining.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return _FakeResponse(outcome)

    monkeypatch.setattr(ha_discovery, "TOKEN", "sup-token")
    monkeypatch.delenv("HBOX_DISCOVERY_HOST", raising=False)
    monkeypatch.setattr(
        ha_discovery, "_supervisor_self_info", lambda: {"hostname": "local-homehoard"})
    monkeypatch.setattr(ha_discovery.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(ha_discovery.time, "sleep", sleeps.append)
    # The local app is ready at once unless a test says otherwise.
    monkeypatch.setattr(ha_discovery, "_ready_probe", lambda: None)
    return posts, sleeps


def test_discovery_retries_until_ha_core_is_up(monkeypatch):
    """HA Core may still be booting: transient failures are retried, and the
    registration happens exactly once when the Supervisor finally answers."""
    posts, sleeps = _discovery_env(monkeypatch, [
        OSError("connection refused"),
        OSError("connection refused"),
        b'{"data": {"uuid": "abc"}}',
    ])

    assert ha_discovery.main() == 0

    assert len(posts) == 3  # two failures, then the one successful POST
    assert sleeps == [2.0, 4.0]


def test_discovery_gives_up_non_fatally_after_bounded_retries(monkeypatch, capsys):
    posts, sleeps = _discovery_env(monkeypatch, [OSError("down")] * 6)

    assert ha_discovery.main() == 0  # never blocks or fails startup

    assert len(posts) == 6
    assert sleeps == [2.0, 4.0, 8.0, 16.0, 32.0]  # ~62 s of backoff, capped at 60
    out = capsys.readouterr().out
    assert "attempt 6/6" in out
    assert "Discovery registration failed (non-fatal)" in out


def test_discovery_waits_for_local_readiness_before_posting(monkeypatch):
    """HA must not be offered a setup before the app can serve it: the POST
    happens only after the /ready probe succeeds."""
    posts, sleeps = _discovery_env(monkeypatch, [b'{"data": {"uuid": "abc"}}'])
    events = []
    probes = [OSError("refused"), OSError("refused"), None]

    def fake_probe():
        events.append(("probe", len(posts)))
        outcome = probes.pop(0)
        if outcome is not None:
            raise outcome

    monkeypatch.setattr(ha_discovery, "_ready_probe", fake_probe)

    assert ha_discovery.main() == 0

    # Every probe ran while nothing had been posted; the POST came after.
    assert events == [("probe", 0)] * 3
    assert len(posts) == 1
    assert sleeps == [2.0, 4.0]  # readiness backoff only; the POST succeeded first try


def test_discovery_posts_anyway_when_never_ready(monkeypatch, capsys):
    posts, sleeps = _discovery_env(monkeypatch, [b'{"data": {"uuid": "abc"}}'])

    def never_ready():
        raise OSError("refused")

    monkeypatch.setattr(ha_discovery, "_ready_probe", never_ready)

    assert ha_discovery.main() == 0

    assert len(posts) == 1  # a late offer beats none
    assert sleeps == [2.0, 4.0, 8.0, 16.0, 30.0, 30.0, 30.0, 30.0, 30.0]  # ~3 min, capped at 30
    assert "registering discovery anyway" in capsys.readouterr().out

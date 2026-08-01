"""Security hardening: SSRF at the point of use, safe SPA path joins, log-safe
request values, and credential-free upstream error text.

Each test pins a specific fix from the code-scanning triage. They assert
BEHAVIOUR (a request is not made, a traversal is refused, a secret is redacted)
rather than the shape of the code, so a refactor that keeps the guarantee keeps
the tests green.
"""
from types import SimpleNamespace

import pytest

from app.logsafe import scrub
from app.services.ai.base import safe_upstream_detail
from app.services.ai.provider_config import list_models

# --- SSRF: validate the base URL where it is USED, not only where it is saved --


def _eff(provider, **kw):
    """A minimal effective-settings stand-in (what list_models reads)."""
    base = {"AI_PROVIDER": provider, "OLLAMA_HOST": "", "OLLAMA_API_KEY": "",
            "OLLAMA_CLOUD_HOST": "", "OLLAMA_CLOUD_API_KEY": "",
            "OPENAI_BASE_URL": "", "OPENAI_API_KEY": ""}
    base.update(kw)
    return SimpleNamespace(**base)


def _no_network(monkeypatch):
    """Record whether an HTTP client is ever constructed.

    Returns a dict the test asserts on POSITIVELY. Raising here would be
    swallowed by list_models' `except Exception: return []`, making the test
    pass even with the guard removed — so the guarantee is 'no client was
    built', not 'the call returned []'.
    """
    import httpx

    seen = {"opened": False}

    def spy(*a, **k):
        seen["opened"] = True
        raise AssertionError("network client opened for a blocked URL")

    monkeypatch.setattr(httpx, "Client", spy)
    return seen


def test_link_local_ollama_host_is_refused_without_a_request(monkeypatch):
    # 169.254.169.254 is the cloud metadata endpoint. An operator-supplied value
    # from env/add-on options never passes the /settings/ai guard, so the block
    # has to happen here.
    seen = _no_network(monkeypatch)
    assert list_models(_eff("ollama", OLLAMA_HOST="http://169.254.169.254")) == []
    assert seen["opened"] is False   # blocked BEFORE any client was constructed


def test_link_local_openai_base_url_is_refused_without_a_request(monkeypatch):
    seen = _no_network(monkeypatch)
    assert list_models(_eff("openai", OPENAI_BASE_URL="http://169.254.169.254/v1")) == []
    assert seen["opened"] is False


def test_private_lan_ollama_host_still_reaches_the_provider(monkeypatch):
    """The guard must NOT break a self-hosted Ollama on the LAN/loopback."""
    called = {}

    class _Resp:
        def raise_for_status(self):
            pass

        def json(self):
            return {"models": [{"name": "llama3"}, {"name": "mistral"}]}

    class _Client:
        def __init__(self, *a, **k):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def get(self, url, headers=None):
            called["url"] = url
            return _Resp()

    import httpx
    monkeypatch.setattr(httpx, "Client", _Client)
    out = list_models(_eff("ollama", OLLAMA_HOST="http://192.168.1.50:11434"))
    assert out == ["llama3", "mistral"]
    assert called["url"].startswith("http://192.168.1.50:11434")


# --- SPA path traversal -------------------------------------------------------


def test_spa_serves_a_nested_asset(app, tmp_path, monkeypatch):
    import app as app_pkg

    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "assets" / "app-abc123.js").write_text("console.log(1)")
    (dist / "index.html").write_text("<html></html>")
    monkeypatch.setattr(app_pkg, "_FRONTEND_DIST", str(dist))

    r = app.test_client().get("/assets/app-abc123.js")
    assert r.status_code == 200
    assert b"console.log(1)" in r.data


def test_spa_refuses_traversal_without_erroring(app, tmp_path, monkeypatch):
    """A traversal must not 500 and must not serve a file outside the dist dir —
    it falls through to the SPA index instead.

    Driven through _serve_spa directly, not the URL router: Flask normalises
    "/../x" before routing, which would make an HTTP-level test vacuous. The old
    os.path.join built a real path outside dist and os.path.isfile returned True
    for it — that probe is the defect being fixed here.
    """
    import app as app_pkg
    from app import _serve_spa

    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("<html>spa</html>")
    (tmp_path / "secret.txt").write_text("root:x:0:0:")
    monkeypatch.setattr(app_pkg, "_FRONTEND_DIST", str(dist))

    with app.test_request_context("/"):
        body = _serve_spa("../secret.txt")
        if isinstance(body, tuple):          # the "frontend not built" notice
            rendered = body[0].encode()
        else:                                # a file response (the SPA index)
            body.direct_passthrough = False
            rendered = body.get_data()
    assert b"root:" not in rendered
    assert b"spa" in rendered                # fell through to index.html


# --- Log injection ------------------------------------------------------------


def test_scrub_neutralises_crlf_so_a_log_line_cannot_be_forged():
    forged = "/items\r\nWARNING login ok for admin"
    out = scrub(forged)
    assert "\n" not in out and "\r" not in out
    assert "\\r\\n" in out          # visible escape, not a real newline
    assert "/items" in out          # still readable


def test_scrub_truncates_a_flooding_value():
    assert len(scrub("x" * 5000)) <= 201


# --- Upstream error text carries no credentials -------------------------------


@pytest.mark.parametrize("raw, secret", [
    ("Incorrect API key provided: sk-proj-AbCdEf123456789", "sk-proj-AbCdEf"),
    ("auth failed for xai-abcdef1234567890ABCDEF", "xai-abcdef"),
    ("Incorrect API key provided: AIzaSyD1234567890abcdefghijklmnopqrs", "AIzaSyD1234"),
    ('{"api_key": "AIzaSyRealGoogleKey123456"}', "AIzaSyReal"),
    ("Authorization: Bearer abcdef1234567890XYZ", "abcdef1234567890XYZ"),
    ("connect to https://user:hunter2@api.example.com failed", "hunter2"),
    ("postgresql://hbox:s3cr3tpw@db.internal:5432/homehoard", "s3cr3tpw"),
])
def test_safe_upstream_detail_redacts_credentials(raw, secret):
    assert secret not in safe_upstream_detail(RuntimeError(raw))


def test_safe_upstream_detail_keeps_useful_diagnostics():
    out = safe_upstream_detail(ConnectionRefusedError("connection refused to http://192.168.1.50:11434"))
    assert "192.168.1.50" in out
    assert "connection refused" in out


def test_safe_upstream_detail_truncates_a_long_response_body():
    body = "upstream returned an unexpected error while processing the request. " * 80
    out = safe_upstream_detail(RuntimeError(body))
    assert len(out) < 300
    assert out.endswith("…")

"""The vault passphrase must never reach the LLM provider or chat history.

When the unhide_items tool answers {needsPassphrase: true}, the session is
marked awaiting-vault-phrase. The NEXT inbound message for that session is the
phrase: the server short-circuits — no provider call, vault.unlock directly,
and only a "[vault passphrase]" placeholder lands in history.
"""
import json

from app.extensions import db
from app.models import ChatSession, Item
from app.services import vault
from app.services.ai.base import ChatResult, ToolCall

PHRASE = "open sesame 42"
REDACTED = "[vault passphrase]"


class _NeverCalledProvider:
    """Any provider call during a vault-phrase turn is the leak this feature closes."""
    name = "never"

    def available(self):
        return True

    def chat(self, *a, **k):
        raise AssertionError("provider.chat must not be called on a vault-phrase turn")

    def chat_stream(self, *a, **k):
        raise AssertionError("provider.chat_stream must not be called on a vault-phrase turn")


class _UnhideAskingProvider:
    """Turn 1: calls unhide_items with no phrase. Turn 2: asks the user for it."""
    name = "fake"

    def __init__(self):
        self.calls = 0

    def available(self):
        return True

    def chat(self, messages, system="", tools=None, max_tokens=2048):
        self.calls += 1
        if self.calls == 1:
            return ChatResult(tool_calls=[
                ToolCall(id="1", name="unhide_items", arguments={})])
        return ChatResult(content="What's the vault passphrase?")


def _setup_vault(auth_client, app, gid):
    r = auth_client.post("/api/v1/vault/passphrase", json={"phrase": PHRASE})
    assert r.status_code == 200
    with app.app_context():
        db.session.add(Item(name="Passport", group_id=gid, hidden=True))
        db.session.commit()


def _awaiting_session(app, gid) -> str:
    with app.app_context():
        s = ChatSession(title="t", group_id=gid, awaiting_vault_phrase=True)
        db.session.add(s)
        db.session.commit()
        return s.id


def _messages(auth_client, sid):
    return auth_client.get(f"/api/v1/chat/sessions/{sid}").get_json()["messages"]


def test_needs_passphrase_tool_result_sets_awaiting_flag(auth_client, app, monkeypatch, gid):
    _setup_vault(auth_client, app, gid)
    monkeypatch.setattr("app.api.chat.get_provider", lambda: _UnhideAskingProvider())

    r = auth_client.post("/api/v1/chat", json={"message": "show my hidden stuff"})

    assert r.status_code == 200
    sid = r.get_json()["sessionId"]
    with app.app_context():
        assert db.session.get(ChatSession, sid).awaiting_vault_phrase is True


def test_phrase_turn_never_calls_provider_and_history_is_redacted(
        auth_client, app, monkeypatch, gid):
    _setup_vault(auth_client, app, gid)
    sid = _awaiting_session(app, gid)
    monkeypatch.setattr("app.api.chat.get_provider", lambda: _NeverCalledProvider())

    r = auth_client.post("/api/v1/chat", json={"message": PHRASE, "sessionId": sid})

    assert r.status_code == 200
    body = r.get_json()
    assert "Unlocked" in body["reply"]
    msgs = _messages(auth_client, sid)
    all_text = json.dumps(msgs)
    assert PHRASE not in all_text
    assert any(m["role"] == "user" and m["content"] == REDACTED for m in msgs)


def test_correct_phrase_unlocks_this_credential_only(auth_client, client, app, monkeypatch, gid):
    _setup_vault(auth_client, app, gid)
    sid = _awaiting_session(app, gid)
    monkeypatch.setattr("app.api.chat.get_provider", lambda: _NeverCalledProvider())

    r = auth_client.post("/api/v1/chat", json={"message": PHRASE, "sessionId": sid})

    assert r.status_code == 200
    # This credential is unlocked…
    assert auth_client.get("/api/v1/vault/status").get_json()["locked"] is False
    # …and the flag is cleared: the next message is normal chat again.
    with app.app_context():
        assert db.session.get(ChatSession, sid).awaiting_vault_phrase is False
    # A different credential stays locked. NOT a second login: this app's JWT
    # is a pure function of its claims at SECOND resolution, so two logins
    # inside the same second return the byte-identical token and are the same
    # credential — this exact assertion flaked in CI on that collision (the
    # same trap test_vault.py documents). An API token is unambiguously
    # distinct, and the case that matters most: an automation must never
    # inherit a human's unlock.
    api_tok = auth_client.post("/api/v1/tokens",
                               json={"name": "bot"}).get_json()["token"]
    r2 = client.get("/api/v1/vault/status",
                    headers={"Authorization": f"Bearer {api_tok}"})
    assert r2.get_json()["locked"] is True


def test_wrong_phrase_stays_locked_and_clears_flag(auth_client, app, monkeypatch, gid):
    _setup_vault(auth_client, app, gid)
    sid = _awaiting_session(app, gid)
    monkeypatch.setattr("app.api.chat.get_provider", lambda: _NeverCalledProvider())

    r = auth_client.post("/api/v1/chat",
                         json={"message": "not the phrase", "sessionId": sid})

    assert r.status_code == 200
    assert "isn't right" in r.get_json()["reply"]
    assert auth_client.get("/api/v1/vault/status").get_json()["locked"] is True
    with app.app_context():
        # Cleared: a retry goes back through the tool ask, never straight to the LLM.
        assert db.session.get(ChatSession, sid).awaiting_vault_phrase is False
    # The wrong attempt is still a secret attempt — never stored verbatim.
    assert "not the phrase" not in json.dumps(_messages(auth_client, sid))


def test_streaming_phrase_turn_short_circuits_and_redacts(auth_client, app, monkeypatch, gid):
    _setup_vault(auth_client, app, gid)
    sid = _awaiting_session(app, gid)
    monkeypatch.setattr("app.api.chat.get_provider", lambda: _NeverCalledProvider())

    r = auth_client.post("/api/v1/chat/stream",
                         json={"message": PHRASE, "sessionId": sid})

    assert r.status_code == 200
    events = [json.loads(ln) for ln in r.get_data(as_text=True).splitlines() if ln.strip()]
    done = events[-1]
    assert done["type"] == "done"
    assert "Unlocked" in done["reply"]
    assert PHRASE not in json.dumps(_messages(auth_client, sid))
    with app.app_context():
        assert db.session.get(ChatSession, sid).awaiting_vault_phrase is False


def test_streaming_needs_passphrase_sets_flag(auth_client, app, monkeypatch, gid):
    _setup_vault(auth_client, app, gid)

    class _StreamAsking:
        name = "fakestream"

        def __init__(self):
            self.calls = 0

        def available(self):
            return True

        def chat_stream(self, messages, system="", tools=None, max_tokens=2048):
            self.calls += 1
            if self.calls == 1:
                yield {"type": "final", "result": ChatResult(
                    tool_calls=[ToolCall(id="1", name="unhide_items", arguments={})])}
                return
            yield {"type": "final",
                   "result": ChatResult(content="What's the vault passphrase?")}

    monkeypatch.setattr("app.api.chat.get_provider", lambda: _StreamAsking())

    r = auth_client.post("/api/v1/chat/stream", json={"message": "unhide my stuff"})
    events = [json.loads(ln) for ln in r.get_data(as_text=True).splitlines() if ln.strip()]
    sid = events[-1]["sessionId"]
    with app.app_context():
        assert db.session.get(ChatSession, sid).awaiting_vault_phrase is True


def test_normal_chat_unaffected_when_flag_unset(auth_client, app, monkeypatch, gid):
    """A session without the flag goes through the provider, message stored verbatim."""
    _setup_vault(auth_client, app, gid)

    class _Echo:
        name = "fake"

        def available(self):
            return True

        def chat(self, messages, system="", tools=None, max_tokens=2048):
            return ChatResult(content="hello back")

    monkeypatch.setattr("app.api.chat.get_provider", lambda: _Echo())

    r = auth_client.post("/api/v1/chat", json={"message": "just chatting"})

    assert r.status_code == 200 and r.get_json()["reply"] == "hello back"
    msgs = _messages(auth_client, r.get_json()["sessionId"])
    assert msgs[0]["content"] == "just chatting"


# --- passphrase guesses share the vault endpoint's rate limit ---------------

import pytest  # noqa: E402

from app import create_app  # noqa: E402
from app.config import Config  # noqa: E402
from app.extensions import limiter  # noqa: E402
from app.models import User  # noqa: E402


@pytest.fixture()
def limited(tmp_path):
    """(client, app, gid) with the real limiter enabled (it is off in `app`)."""
    class LimitedConfig(Config):
        DATA_DIR = str(tmp_path)
        DATABASE_URL = f"sqlite:///{tmp_path}/test.db"
        DISABLE_AUTH = False
        SECRET_KEY = "test-secret-key-that-is-long-enough-32b"
        RATELIMIT_ENABLED = True
        RATELIMIT_STORAGE_URI = "memory://"
        PROXY_HOPS = 0
        WORKER_ENABLED = False

    app = create_app(LimitedConfig)
    c = app.test_client()
    c.post("/api/v1/users/register",
           json={"email": "t@t.com", "password": "password", "name": "T"})
    tok = c.post("/api/v1/users/login",
                 json={"username": "t@t.com", "password": "password"}).get_json()["token"]
    c.environ_base["HTTP_AUTHORIZATION"] = tok
    with app.app_context():
        gid = db.session.query(User).filter_by(email="t@t.com").one().group_id
    yield c, app, gid
    limiter.reset()
    with app.app_context():
        db.session.remove()
        db.drop_all()


def _chat_guess(c, app, gid, phrase="wrong guess"):
    sid = _awaiting_session(app, gid)
    return c.post("/api/v1/chat", json={"message": phrase, "sessionId": sid})


def test_chat_phrase_guesses_are_capped_without_calling_unlock(limited, monkeypatch):
    c, app, gid = limited
    _setup_vault(c, app, gid)
    calls = []
    real = vault.unlock
    monkeypatch.setattr("app.api.chat.vault.unlock",
                        lambda *a, **k: calls.append(1) or real(*a, **k))

    replies = [_chat_guess(c, app, gid).get_json()["reply"] for _ in range(10)]
    assert all("isn't right" in r for r in replies)
    assert len(calls) == 10

    r = _chat_guess(c, app, gid, phrase=PHRASE)  # even the RIGHT phrase is refused
    assert r.status_code == 200
    assert "Too many passphrase attempts" in r.get_json()["reply"]
    assert len(calls) == 10  # no 11th unlock attempt
    assert c.get("/api/v1/vault/status").get_json()["locked"] is True


def test_endpoint_and_chat_attempts_share_one_counter(limited):
    c, app, gid = limited
    _setup_vault(c, app, gid)
    for _ in range(5):
        assert c.post("/api/v1/vault/unlock", json={"phrase": "nope"}).status_code == 403
    for _ in range(5):
        assert "isn't right" in _chat_guess(c, app, gid).get_json()["reply"]
    # 10 attempts used across both doors: both are now closed.
    assert c.post("/api/v1/vault/unlock", json={"phrase": PHRASE}).status_code == 429
    assert "Too many" in _chat_guess(c, app, gid, phrase=PHRASE).get_json()["reply"]


# --- provider errors are curated --------------------------------------------

from app.services.ai.base import ProviderError  # noqa: E402

LEAK = "claude request failed: 401 sk-ant-SECRET body={'detail':'upstream-secret'}"


class _FailingProvider:
    name = "fail"

    def available(self):
        return True

    def chat(self, *a, **k):
        raise ProviderError(LEAK)

    def chat_stream(self, *a, **k):
        raise ProviderError(LEAK)
        yield  # pragma: no cover


def test_chat_502_hides_upstream_text_and_gives_a_ref(auth_client, monkeypatch, caplog):
    monkeypatch.setattr("app.api.chat.get_provider", lambda: _FailingProvider())
    with caplog.at_level("WARNING", logger="homehoard.chat"):
        r = auth_client.post("/api/v1/chat", json={"message": "hi"})
    assert r.status_code == 502
    err = r.get_json()["error"]
    assert err.startswith("The AI provider returned an error (ref ")
    assert "upstream-secret" not in err and "claude request failed" not in err
    assert any("ProviderError" in m for m in caplog.messages)  # detail logged, not sent


def test_chat_stream_error_event_hides_upstream_text(auth_client, monkeypatch):
    monkeypatch.setattr("app.api.chat.get_provider", lambda: _FailingProvider())
    r = auth_client.post("/api/v1/chat/stream", json={"message": "hi"})
    events = [json.loads(line) for line in r.get_data(as_text=True).splitlines() if line]
    err = [e for e in events if e["type"] == "error"][0]["error"]
    assert err.startswith("The AI provider returned an error (ref ")
    assert "upstream-secret" not in err and "claude request failed" not in err

"""The vault passphrase must never reach the LLM provider or chat history.

When the unhide_items tool answers {needsPassphrase: true}, the session is
marked awaiting-vault-phrase. The NEXT inbound message for that session is the
phrase: the server short-circuits — no provider call, vault.unlock directly,
and only a "[vault passphrase]" placeholder lands in history.
"""
import json

from app.extensions import db
from app.models import ChatSession, Item
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
    # A different credential (fresh login = new token) stays locked.
    token2 = client.post(
        "/api/v1/users/login",
        json={"username": "t@t.com", "password": "password"}).get_json()["token"]
    r2 = client.get("/api/v1/vault/status",
                    headers={"Authorization": token2})
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

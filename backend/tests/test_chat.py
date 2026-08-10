"""Chat assistant: provider-agnostic tool loop, session persistence, guards.

Uses a fake provider (no live vendor call). The fake returns one tool call, then a
final answer — exercising the real execute_tool path against the group's data.
"""
from app.extensions import db
from app.models import ChatSession, Group, Item, Label
from app.services.ai.base import ChatResult, ProviderError, ToolCall


class _FakeProvider:
    name = "fake"

    def __init__(self):
        self.calls = 0

    def available(self):
        return True

    def chat(self, messages, system="", tools=None, max_tokens=2048):
        self.calls += 1
        if self.calls == 1:
            return ChatResult(tool_calls=[
                ToolCall(id="1", name="search_items", arguments={"query": "drill"})])
        return ChatResult(content="Your drill is in the Garage.")


def _seed_item(app, gid, name="DeWalt drill"):
    with app.app_context():
        db.session.add(Item(name=name, group_id=gid))
        db.session.commit()


def test_chat_creates_session_and_runs_tool_loop(auth_client, app, monkeypatch, gid):
    _seed_item(app, gid)
    monkeypatch.setattr("app.api.chat.get_provider", lambda: _FakeProvider())

    r = auth_client.post("/api/v1/chat", json={"message": "where is my drill?"})

    assert r.status_code == 200
    body = r.get_json()
    assert "Garage" in body["reply"] and body["sessionId"]

    convo = auth_client.get(f"/api/v1/chat/sessions/{body['sessionId']}").get_json()
    assert [m["role"] for m in convo["messages"]] == ["user", "assistant"]
    # The assistant message records the tool it invoked.
    assert convo["messages"][1]["toolTrace"][0]["tool"] == "search_items"


def test_chat_continues_existing_session(auth_client, app, monkeypatch, gid):
    _seed_item(app, gid)
    monkeypatch.setattr("app.api.chat.get_provider", lambda: _FakeProvider())
    first = auth_client.post("/api/v1/chat", json={"message": "hi"}).get_json()
    auth_client.post("/api/v1/chat",
                     json={"message": "and the drill?", "sessionId": first["sessionId"]})
    convo = auth_client.get(f"/api/v1/chat/sessions/{first['sessionId']}").get_json()
    assert len(convo["messages"]) == 4  # two turns


def test_chat_without_provider_returns_503(auth_client):
    assert auth_client.post("/api/v1/chat", json={"message": "hi"}).status_code == 503


def test_chat_message_required_422(auth_client, monkeypatch):
    monkeypatch.setattr("app.api.chat.get_provider", lambda: _FakeProvider())
    assert auth_client.post("/api/v1/chat", json={"message": "  "}).status_code == 422


def test_chat_session_cross_group_is_404(auth_client, app):
    with app.app_context():
        other = Group(name="Other", currency="usd")
        db.session.add(other)
        db.session.flush()
        sess = ChatSession(title="theirs", group_id=other.id)
        db.session.add(sess)
        db.session.commit()
        sid = sess.id
    assert auth_client.get(f"/api/v1/chat/sessions/{sid}").status_code == 404
    assert auth_client.delete(f"/api/v1/chat/sessions/{sid}").status_code == 404


class _WriteThenFailProvider:
    """Calls a write tool on turn 1, then the upstream dies on turn 2."""

    name = "fake"

    def __init__(self):
        self.calls = 0

    def available(self):
        return True

    def chat(self, messages, system="", tools=None, max_tokens=2048):
        self.calls += 1
        if self.calls == 1:
            return ChatResult(tool_calls=[ToolCall(
                id="1", name="add_label_to_item",
                arguments={"item": "Drill", "label": "Tools"})])
        raise ProviderError("upstream down")


def test_chat_provider_error_midloop_leaves_no_phantom_or_orphan_write(auth_client, app, monkeypatch, gid):

    with app.app_context():
        db.session.add(Item(name="Drill", group_id=gid))
        db.session.add(Label(name="Tools", group_id=gid))
        db.session.commit()
    monkeypatch.setattr("app.api.chat.get_provider", lambda: _WriteThenFailProvider())

    r = auth_client.post("/api/v1/chat", json={"message": "tag the drill"})

    assert r.status_code == 502
    with app.app_context():
        # The transaction rolled back: no session row, and the label write is gone.
        assert db.session.query(ChatSession).count() == 0
        it = db.session.query(Item).filter_by(name="Drill").first()
        assert all(lb.name != "Tools" for lb in it.labels)


class _ToolThenAnswerProvider:
    name = "fake"

    def __init__(self):
        self.calls = 0

    def available(self):
        return True

    def chat(self, messages, system="", tools=None, max_tokens=2048):
        self.calls += 1
        if self.calls == 1:
            return ChatResult(tool_calls=[ToolCall(id="1", name="search_items",
                                                   arguments={"query": "x"})])
        return ChatResult(content="Done, though a lookup hiccupped.")


def test_chat_tool_exception_is_fed_back_not_500(auth_client, monkeypatch, gid):
    monkeypatch.setattr("app.api.chat.get_provider", lambda: _ToolThenAnswerProvider())

    def _boom(gid, name, args):
        raise RuntimeError("kaboom")
    monkeypatch.setattr("app.services.ai.agent.execute_tool", _boom)

    r = auth_client.post("/api/v1/chat", json={"message": "find x"})

    assert r.status_code == 200  # tool error fed back to the model, not a 500
    convo = auth_client.get(f"/api/v1/chat/sessions/{r.get_json()['sessionId']}").get_json()
    assert len(convo["messages"]) == 2
    assert "kaboom" in str(convo["messages"][1]["toolTrace"])

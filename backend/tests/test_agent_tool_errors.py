"""A failing tool must not leak raw exception text to the model or the client.

Typed domain errors (FieldValidationError / werkzeug HTTPException, JobError) carry a
curated message and pass through; anything else is logged with a ref id and the
model, the stream, the response and the stored trace see only that ref.
"""
import json
import logging

from app.api._validation import FieldValidationError
from app.extensions import db
from app.models import Item
from app.services.ai.base import ChatResult, ToolCall
from app.services.jobs import JobError

SECRET = "s3cret"
LEAKY = RuntimeError(f"connection failed: postgresql://u:{SECRET}@h/db")


class _Provider:
    """Turn 1 asks for one tool; turn 2 answers. Records what the model was fed."""
    name = "fake"

    def __init__(self):
        self.calls = 0
        self.seen: list = []

    def available(self):
        return True

    def _turn(self, messages):
        self.calls += 1
        self.seen.append(json.dumps(messages))
        if self.calls == 1:
            return ChatResult(tool_calls=[
                ToolCall(id="1", name="search_items", arguments={"query": "x"})])
        return ChatResult(content="done")

    def chat(self, messages, system="", tools=None, max_tokens=2048):
        return self._turn(messages)

    def chat_stream(self, messages, system="", tools=None, max_tokens=2048):
        yield {"type": "final", "result": self._turn(messages)}


def _raising(exc):
    def _tool(gid, name, args):
        raise exc
    return _tool


def _setup(monkeypatch, exc):
    prov = _Provider()
    monkeypatch.setattr("app.api.chat.get_provider", lambda: prov)
    monkeypatch.setattr("app.services.ai.agent.execute_tool", _raising(exc))
    return prov


def _stored_trace(client, session_id):
    convo = client.get(f"/api/v1/chat/sessions/{session_id}").get_json()
    return convo["messages"][1]["toolTrace"]


def test_untyped_error_is_redacted_from_model_response_and_trace(
        auth_client, monkeypatch, caplog):
    prov = _setup(monkeypatch, LEAKY)
    with caplog.at_level(logging.ERROR, logger="homehoard.ai.agent"):
        r = auth_client.post("/api/v1/chat", json={"message": "find x"})
    assert r.status_code == 200
    body = r.get_data(as_text=True)
    assert SECRET not in body
    assert all(SECRET not in s for s in prov.seen)  # the model never saw it
    trace = _stored_trace(auth_client, r.get_json()["sessionId"])
    assert SECRET not in json.dumps(trace)
    err = trace[0]["result"]["error"]
    assert err.startswith("search_items failed (internal error, ref ")
    # The detail is not lost: it is in the server log, under the same ref.
    ref = err.rsplit("ref ", 1)[1].rstrip(")")
    rec = [r for r in caplog.records if ref in r.getMessage()]
    assert rec and rec[0].exc_info and SECRET in str(rec[0].exc_info[1])


def test_untyped_error_is_redacted_from_stream(auth_client, monkeypatch):
    prov = _setup(monkeypatch, LEAKY)
    r = auth_client.post("/api/v1/chat/stream", json={"message": "find x"})
    assert r.status_code == 200
    text = r.get_data(as_text=True)
    assert SECRET not in text
    assert all(SECRET not in s for s in prov.seen)
    done = [json.loads(ln) for ln in text.splitlines() if ln.strip()][-1]
    assert done["type"] == "done"
    assert SECRET not in json.dumps(_stored_trace(auth_client, done["sessionId"]))
    assert "internal error, ref " in text


def test_field_validation_error_message_passes_through(auth_client, monkeypatch):
    prov = _setup(monkeypatch, FieldValidationError(
        {"quantity": "Quantity must be positive"}, "Quantity must be positive"))
    r = auth_client.post("/api/v1/chat", json={"message": "find x"})
    result = _stored_trace(auth_client, r.get_json()["sessionId"])[0]["result"]
    assert result["error"] == "search_items failed: Quantity must be positive"
    assert result["fields"] == {"quantity": "Quantity must be positive"}
    assert "Quantity must be positive" in prov.seen[1]  # the model can self-correct


def test_job_error_message_passes_through(auth_client, monkeypatch):
    _setup(monkeypatch, JobError("Web search isn't configured."))
    r = auth_client.post("/api/v1/chat", json={"message": "find x"})
    result = _stored_trace(auth_client, r.get_json()["sessionId"])[0]["result"]
    assert result == {"error": "search_items failed: Web search isn't configured."}


def test_failed_tool_write_is_rolled_back(auth_client, app, monkeypatch, gid):
    def _write_then_fail(g, name, args):
        db.session.add(Item(name="half-made", group_id=g))
        db.session.flush()
        raise LEAKY
    prov = _Provider()
    monkeypatch.setattr("app.api.chat.get_provider", lambda: prov)
    monkeypatch.setattr("app.services.ai.agent.execute_tool", _write_then_fail)
    r = auth_client.post("/api/v1/chat", json={"message": "find x"})
    assert r.status_code == 200
    with app.app_context():
        assert db.session.query(Item).filter_by(name="half-made").count() == 0

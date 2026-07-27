"""Conversational HomeHoard-assistant endpoints.

A chat surface over the same inventory the app already exposes: the model looks
things up with tools and answers. Sessions + messages are group-scoped and
persisted so a conversation survives a reload.
"""
import json

from flask import Blueprint, request, jsonify, abort

from ..extensions import db, limiter
from ..models import ChatSession, ChatMessage, utcnow
from ..auth import login_required, current_group
from ..schemas.serializers import (
    chat_session_out, chat_session_summary, chat_message_out,
)
from ..services.ai.base import ProviderError
from ..services.ai.registry import get_provider
from ..services.ai.agent import run_chat, actions_from_trace

bp = Blueprint("chat", __name__)


def _get_session(session_id) -> ChatSession:
    s = db.session.get(ChatSession, session_id)
    if not s or s.group_id != current_group().id:
        abort(404)
    return s


@bp.get("/chat/sessions")
@login_required
def list_sessions():
    sessions = (
        db.session.query(ChatSession)
        .filter_by(group_id=current_group().id)
        .order_by(ChatSession.updated_at.desc())
        .all()
    )
    return jsonify({"items": [chat_session_summary(s) for s in sessions]})


@bp.get("/chat/sessions/<session_id>")
@login_required
def get_session(session_id):
    return jsonify(chat_session_out(_get_session(session_id)))


@bp.delete("/chat/sessions/<session_id>")
@login_required
def delete_session(session_id):
    db.session.delete(_get_session(session_id))
    db.session.commit()
    return "", 204


def _next_position(session) -> int:
    return (max((m.position for m in session.messages), default=-1)) + 1


@bp.post("/chat")
@login_required
@limiter.limit("30 per minute")
def chat():
    """Send a message to the assistant. Creates a session if none is given."""
    data = request.get_json(force=True) or {}
    message = str(data.get("message") or "").strip()
    if not message:
        return jsonify({"error": "message is required"}), 422

    try:
        provider = get_provider()
    except ProviderError as exc:
        return jsonify({"error": str(exc)}), 503

    gid = current_group().id
    session_id = data.get("sessionId")
    if session_id:
        session = _get_session(session_id)
    else:
        session = ChatSession(title=message[:60] or "New chat", group_id=gid)
        db.session.add(session)
        db.session.flush()

    history = [{"role": m.role, "content": m.content} for m in session.messages]

    try:
        result = run_chat(gid, provider, history, message)
    except ProviderError as exc:
        # Discard the flushed-but-uncommitted session so a failed turn leaves no
        # phantom session behind.
        db.session.rollback()
        return jsonify({"error": str(exc)}), 502

    pos = _next_position(session)
    user_msg = ChatMessage(role="user", content=message, position=pos, session_id=session.id)
    assistant_msg = ChatMessage(
        role="assistant", content=result["reply"],
        tool_trace=json.dumps(result["trace"]), position=pos + 1, session_id=session.id)
    db.session.add_all([user_msg, assistant_msg])
    # Touch the parent so most-recently-used sessions sort first (adding child
    # messages alone doesn't fire the session's onupdate).
    session.updated_at = utcnow()
    db.session.commit()

    return jsonify({
        "sessionId": session.id,
        "reply": result["reply"],
        "actions": actions_from_trace(result["trace"]),
        "message": chat_message_out(assistant_msg),
    })

from sqlalchemy import Boolean, ForeignKey, Integer, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..extensions import db
from .base import IDMixin, TimestampMixin


class ChatSession(IDMixin, TimestampMixin, db.Model):
    """A conversation with the HomeHoard assistant, scoped to a group."""

    __tablename__ = "chat_sessions"

    title: Mapped[str] = mapped_column(String(255), default="New chat")

    group_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("groups.id"), index=True)

    # Set when a tool answered {needsPassphrase: true}: the NEXT inbound message
    # for this session is the vault passphrase and is short-circuited server-side
    # (api/chat.py) — it must never reach the LLM provider or the stored history.
    awaiting_vault_phrase: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=text("0"), nullable=False)
    group = relationship("Group", back_populates="chat_sessions")

    messages = relationship(
        "ChatMessage",
        back_populates="session",
        cascade="all, delete-orphan",
        order_by="ChatMessage.position",
    )


class ChatMessage(IDMixin, TimestampMixin, db.Model):
    __tablename__ = "chat_messages"

    # role: user | assistant
    role: Mapped[str] = mapped_column(String(16))
    content: Mapped[str] = mapped_column(Text, default="")
    position: Mapped[int] = mapped_column(Integer, default=0)
    # JSON summary of any tools the assistant invoked on this turn (display only).
    tool_trace: Mapped[str] = mapped_column(Text, default="")

    session_id: Mapped[str] = mapped_column(String(36), ForeignKey("chat_sessions.id"))
    session = relationship("ChatSession", back_populates="messages")

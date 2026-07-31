"""Long-lived API tokens (API keys).

Unlike the short-lived login JWTs, these do not expire and are meant for
machine clients — most notably the Home Assistant integration polling
``/ha/summary`` and ``/search`` when app auth is enabled. Only a SHA-256 hash
is stored; the raw token is shown to the user exactly once at creation.
"""
import hashlib
import secrets

from sqlalchemy import String, DateTime, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..extensions import db
from .base import IDMixin, TimestampMixin

# Raw tokens carry this prefix so the auth layer can tell them apart from a JWT
# without a database round-trip, and so users recognize a HomeHoard key.
TOKEN_PREFIX = "hh_"

# Per-key access scope. `full` reaches everything (default for legacy keys); `rest`
# is REST-only (no MCP); `mcp` is issued for the MCP transport alone and is REJECTED
# at the REST API (see auth._user_from_api_token).
TOKEN_SCOPES = ("full", "rest", "mcp")

# Per-key access class, orthogonal to scope: `write` (default) can read AND mutate;
# `read` is read-only — the REST API rejects non-GET/HEAD requests and the MCP guard
# rejects mutating tool calls. Legacy rows default to "write".
TOKEN_ACCESS = ("write", "read")


def generate_raw_token() -> str:
    return TOKEN_PREFIX + secrets.token_urlsafe(32)


def hash_token(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


class ApiToken(IDMixin, TimestampMixin, db.Model):
    __tablename__ = "api_tokens"

    name: Mapped[str] = mapped_column(String(255), default="")
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    # full | rest | mcp — see TOKEN_SCOPES. Legacy rows default to "full".
    scope: Mapped[str] = mapped_column(String(16), default="full", server_default="full")
    # write | read — see TOKEN_ACCESS. A read key is read-only on REST and MCP.
    access: Mapped[str] = mapped_column(String(8), default="write", server_default="write")
    # First few chars of the raw token, kept for display ("hh_ab12…").
    hint: Mapped[str] = mapped_column(String(16), default="")
    last_used_at: Mapped[str] = mapped_column(DateTime, nullable=True)

    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"))
    group_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("groups.id"), index=True
    )
    user = relationship("User", back_populates="api_tokens")

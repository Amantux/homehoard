from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from ..extensions import db
from .base import IDMixin, TimestampMixin


class VaultUnlock(IDMixin, TimestampMixin, db.Model):
    """One live unlock: this credential, in this household, until it expires.

    Stored in the DATABASE rather than process memory on purpose — the app runs
    several gunicorn workers, so an in-process dict would unlock only whichever
    worker happened to serve the request and appear to randomly re-lock.

    A row is keyed by `credential_fingerprint`, the sha256 of the presented
    Authorization credential (the same `hash_token` used for API tokens). That
    is what makes an unlock apply to ONE session: a JWT login and an API token
    are different credentials, so unlocking in chat leaves another device — and
    another household member — still seeing nothing.
    """
    __tablename__ = "vault_unlocks"

    group_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("groups.id"), index=True)
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id"), nullable=True)
    # sha256 of the credential — never the credential itself.
    credential_fingerprint: Mapped[str] = mapped_column(
        String(64), index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=True)

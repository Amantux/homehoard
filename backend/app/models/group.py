from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..extensions import db
from .base import IDMixin, TimestampMixin


class Group(IDMixin, TimestampMixin, db.Model):
    __tablename__ = "groups"

    name: Mapped[str] = mapped_column(String(255))
    currency: Mapped[str] = mapped_column(String(8), default="usd")
    # bcrypt hash of the vault passphrase, or "" when no vault is configured.
    # NEVER the phrase itself. AppSetting would be the wrong home: it is
    # instance-global, and this is one household's secret.
    vault_passphrase_hash: Mapped[str] = mapped_column(
        String(255), default="", server_default="", nullable=False)

    users = relationship("User", back_populates="group", cascade="all, delete-orphan")
    locations = relationship(
        "Location", back_populates="group", cascade="all, delete-orphan"
    )
    labels = relationship("Label", back_populates="group", cascade="all, delete-orphan")
    items = relationship("Item", back_populates="group", cascade="all, delete-orphan")
    bins = relationship("Bin", back_populates="group", cascade="all, delete-orphan")
    qr_tags = relationship(
        "QrTag", back_populates="group", cascade="all, delete-orphan"
    )
    notifiers = relationship(
        "Notifier", back_populates="group", cascade="all, delete-orphan"
    )
    invitations = relationship(
        "GroupInvitation", back_populates="group", cascade="all, delete-orphan"
    )
    chat_sessions = relationship(
        "ChatSession", back_populates="group", cascade="all, delete-orphan"
    )
    jobs = relationship("Job", back_populates="group", cascade="all, delete-orphan")
    ai_suggestions = relationship(
        "AiSuggestion", back_populates="group", cascade="all, delete-orphan")


class GroupInvitation(IDMixin, TimestampMixin, db.Model):
    __tablename__ = "group_invitations"

    token: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    expires_at: Mapped[str] = mapped_column(String(64))
    uses: Mapped[int] = mapped_column(default=1)

    group_id: Mapped[str] = mapped_column(String(36), db.ForeignKey("groups.id"))
    group = relationship("Group", back_populates="invitations")

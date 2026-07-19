from sqlalchemy import String, Boolean, DateTime, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..extensions import db
from .base import IDMixin, TimestampMixin


class User(IDMixin, TimestampMixin, db.Model):
    __tablename__ = "users"

    name: Mapped[str] = mapped_column(String(255))
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    is_superuser: Mapped[bool] = mapped_column(Boolean, default=False)
    is_owner: Mapped[bool] = mapped_column(Boolean, default=False)
    activated_on: Mapped[str] = mapped_column(String(64), nullable=True)

    group_id: Mapped[str] = mapped_column(String(36), ForeignKey("groups.id"))
    group = relationship("Group", back_populates="users")

    tokens = relationship(
        "AuthToken", back_populates="user", cascade="all, delete-orphan"
    )
    # cascade so deleting a user (delete_self) removes their owned rows. Required
    # now that foreign_keys=ON enforces these FKs (else the delete RESTRICTs → 500).
    notifiers = relationship(
        "Notifier", back_populates="user", cascade="all, delete-orphan"
    )
    api_tokens = relationship(
        "ApiToken", back_populates="user", cascade="all, delete-orphan"
    )


class AuthToken(IDMixin, db.Model):
    __tablename__ = "auth_tokens"

    token: Mapped[str] = mapped_column(String(512), index=True)
    expires_at: Mapped[str] = mapped_column(DateTime)

    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"))
    user = relationship("User", back_populates="tokens")

from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..extensions import db
from .base import IDMixin, TimestampMixin


class Group(IDMixin, TimestampMixin, db.Model):
    __tablename__ = "groups"

    name: Mapped[str] = mapped_column(String(255))
    currency: Mapped[str] = mapped_column(String(8), default="usd")

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


class GroupInvitation(IDMixin, TimestampMixin, db.Model):
    __tablename__ = "group_invitations"

    token: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    expires_at: Mapped[str] = mapped_column(String(64))
    uses: Mapped[int] = mapped_column(default=1)

    group_id: Mapped[str] = mapped_column(String(36), db.ForeignKey("groups.id"))
    group = relationship("Group", back_populates="invitations")

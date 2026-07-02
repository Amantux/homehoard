from sqlalchemy import String, Boolean, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..extensions import db
from .base import IDMixin, TimestampMixin


class Notifier(IDMixin, TimestampMixin, db.Model):
    __tablename__ = "notifiers"

    name: Mapped[str] = mapped_column(String(255))
    url: Mapped[str] = mapped_column(String(2048))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    group_id: Mapped[str] = mapped_column(String(36), ForeignKey("groups.id"))
    group = relationship("Group", back_populates="notifiers")

    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"))
    user = relationship("User", back_populates="notifiers")

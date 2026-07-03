from datetime import datetime

from sqlalchemy import String, Text, DateTime, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..extensions import db
from .base import IDMixin, TimestampMixin


class CheckoutEntry(IDMixin, TimestampMixin, db.Model):
    """A single check-out or check-in event — the lending history for an item."""

    __tablename__ = "checkout_entries"

    action: Mapped[str] = mapped_column(String(8))  # "out" | "in"
    person: Mapped[str] = mapped_column(String(255), default="")
    notes: Mapped[str] = mapped_column(Text, default="")
    due: Mapped[datetime] = mapped_column(DateTime, nullable=True)

    item_id: Mapped[str] = mapped_column(String(36), ForeignKey("items.id"))
    item = relationship("Item", back_populates="checkout_entries")

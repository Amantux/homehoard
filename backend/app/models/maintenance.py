from datetime import datetime

from sqlalchemy import String, Text, Float, DateTime, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..extensions import db
from .base import IDMixin, TimestampMixin


class MaintenanceEntry(IDMixin, TimestampMixin, db.Model):
    __tablename__ = "maintenance_entries"

    name: Mapped[str] = mapped_column(String(255))
    description: Mapped[str] = mapped_column(Text, default="")
    cost: Mapped[float] = mapped_column(Float, default=0.0)
    scheduled_date: Mapped[datetime] = mapped_column(DateTime, nullable=True)
    completed_date: Mapped[datetime] = mapped_column(DateTime, nullable=True)

    item_id: Mapped[str] = mapped_column(String(36), ForeignKey("items.id"))
    item = relationship("Item", back_populates="maintenance_entries")

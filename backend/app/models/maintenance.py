from datetime import datetime
from decimal import Decimal

from sqlalchemy import String, Text, DateTime, ForeignKey, Integer
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..extensions import db
from .base import MONEY, IDMixin, TimestampMixin


class MaintenanceEntry(IDMixin, TimestampMixin, db.Model):
    __tablename__ = "maintenance_entries"

    name: Mapped[str] = mapped_column(String(255))
    description: Mapped[str] = mapped_column(Text, default="")
    # Money is Decimal in the DB, float on the wire (services.money).
    cost: Mapped[Decimal] = mapped_column(MONEY, default=Decimal("0.00"))
    scheduled_date: Mapped[datetime] = mapped_column(DateTime, nullable=True)
    completed_date: Mapped[datetime] = mapped_column(DateTime, nullable=True)
    # Repeat every N calendar months; NULL = one-shot. Completing a recurring
    # entry spawns the next scheduled one (api.maintenance), keeping history.
    recur_months: Mapped[int] = mapped_column(Integer, nullable=True)

    item_id: Mapped[str] = mapped_column(String(36), ForeignKey("items.id"))
    item = relationship("Item", back_populates="maintenance_entries")

    # How-to videos for THIS job (as opposed to the item's general ones).
    # delete-orphan so removing a task takes its videos with it.
    attachments = relationship(
        "Attachment", back_populates="maintenance_entry",
        cascade="all, delete-orphan",
    )

from sqlalchemy import String, Text, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..extensions import db
from .base import IDMixin, TimestampMixin


class Bin(IDMixin, TimestampMixin, db.Model):
    """A container that lives in a location and holds a collection of items.

    Conceptually this is homebox's nested-container pattern made explicit: a
    location contains bins, and a bin contains items.
    """

    __tablename__ = "bins"

    name: Mapped[str] = mapped_column(String(255))
    description: Mapped[str] = mapped_column(Text, default="")

    group_id: Mapped[str] = mapped_column(String(36), ForeignKey("groups.id"))
    group = relationship("Group", back_populates="bins")

    location_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("locations.id"), nullable=True
    )
    location = relationship("Location", back_populates="bins")

    items = relationship("Item", back_populates="bin")
    attachments = relationship(
        "Attachment", back_populates="bin", cascade="all, delete-orphan"
    )

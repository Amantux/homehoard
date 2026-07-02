from sqlalchemy import String, Text, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..extensions import db
from .base import IDMixin, TimestampMixin


class Location(IDMixin, TimestampMixin, db.Model):
    __tablename__ = "locations"

    name: Mapped[str] = mapped_column(String(255))
    description: Mapped[str] = mapped_column(Text, default="")

    group_id: Mapped[str] = mapped_column(String(36), ForeignKey("groups.id"))
    group = relationship("Group", back_populates="locations")

    parent_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("locations.id"), nullable=True
    )
    parent = relationship("Location", remote_side="Location.id", back_populates="children")
    children = relationship(
        "Location", back_populates="parent", cascade="all, delete-orphan"
    )

    items = relationship("Item", back_populates="location")
    bins = relationship(
        "Bin", back_populates="location", cascade="all, delete-orphan"
    )

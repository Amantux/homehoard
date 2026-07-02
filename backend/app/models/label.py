from sqlalchemy import String, Text, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..extensions import db
from .base import IDMixin, TimestampMixin

# Association table between items and labels
item_labels = db.Table(
    "item_labels",
    db.Column("item_id", String(36), ForeignKey("items.id"), primary_key=True),
    db.Column("label_id", String(36), ForeignKey("labels.id"), primary_key=True),
)


class Label(IDMixin, TimestampMixin, db.Model):
    """Also known as a Tag in newer homebox. Supports color, icon and nesting."""

    __tablename__ = "labels"

    name: Mapped[str] = mapped_column(String(255))
    description: Mapped[str] = mapped_column(Text, default="")
    color: Mapped[str] = mapped_column(String(16), default="")
    icon: Mapped[str] = mapped_column(String(255), default="")

    group_id: Mapped[str] = mapped_column(String(36), ForeignKey("groups.id"))
    group = relationship("Group", back_populates="labels")

    parent_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("labels.id"), nullable=True
    )
    parent = relationship("Label", remote_side="Label.id", back_populates="children")
    children = relationship("Label", back_populates="parent")

    items = relationship("Item", secondary=item_labels, back_populates="labels")

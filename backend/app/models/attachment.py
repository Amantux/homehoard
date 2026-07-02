from sqlalchemy import String, Boolean, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..extensions import db
from .base import IDMixin, TimestampMixin


class Document(IDMixin, TimestampMixin, db.Model):
    """A stored file on disk, referenced by attachments."""

    __tablename__ = "documents"

    title: Mapped[str] = mapped_column(String(255))
    path: Mapped[str] = mapped_column(String(1024))

    group_id: Mapped[str] = mapped_column(String(36), ForeignKey("groups.id"))

    attachment = relationship(
        "Attachment", back_populates="document", uselist=False,
        cascade="all, delete-orphan",
    )


class Attachment(IDMixin, TimestampMixin, db.Model):
    __tablename__ = "attachments"

    # type: attachment | manual | warranty | wifi | photo | receipt
    type: Mapped[str] = mapped_column(String(50), default="attachment")
    primary: Mapped[bool] = mapped_column(Boolean, default=False)

    item_id: Mapped[str] = mapped_column(String(36), ForeignKey("items.id"))
    item = relationship("Item", back_populates="attachments")

    document_id: Mapped[str] = mapped_column(String(36), ForeignKey("documents.id"))
    document = relationship("Document", back_populates="attachment")

from typing import Optional

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
    """A file or a link hanging off an item, a bin, or a maintenance task.

    Two shapes share this table, and exactly one of them applies to any row:

    * a **file** — ``document_id`` points at a Document on disk;
    * a **link** — ``url`` holds an external address and there is no Document.

    ``document_id`` is nullable for the link case. The one-parent /
    one-source invariant is enforced in ``services.attachments.validate``
    rather than by a database constraint, so the error reaches the caller as a
    422 with a message instead of an IntegrityError.
    """

    __tablename__ = "attachments"

    # type: attachment | manual | warranty | wifi | photo | receipt | video
    type: Mapped[str] = mapped_column(String(50), default="attachment")
    primary: Mapped[bool] = mapped_column(Boolean, default=False)

    # An attachment belongs to exactly one of: an item, a bin, or a maintenance
    # entry. The last lets a how-to video hang off the specific job it explains
    # rather than off the whole appliance.
    item_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("items.id"), nullable=True
    )
    item = relationship("Item", back_populates="attachments")

    bin_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("bins.id"), nullable=True
    )
    bin = relationship("Bin", back_populates="attachments")

    maintenance_entry_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("maintenance_entries.id"), nullable=True, index=True
    )
    maintenance_entry = relationship("MaintenanceEntry", back_populates="attachments")

    # Nullable: a linked video has no file on disk.
    document_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("documents.id"), nullable=True
    )
    document = relationship("Document", back_populates="attachment")

    # Set for a link; empty for a file. 2048 is the practical URL ceiling.
    url: Mapped[str] = mapped_column(String(2048), default="", server_default="")

    # Display name. Lives here rather than only on Document because a LINK has
    # no Document — and giving links a file-less Document row purely to hold a
    # title made the "file or link, never both" invariant incoherent.
    title: Mapped[str] = mapped_column(String(255), default="", server_default="")

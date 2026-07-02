import secrets

from sqlalchemy import String, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..extensions import db
from .base import IDMixin, TimestampMixin


def gen_token() -> str:
    # Short, URL-safe, unambiguous token for printed QR codes.
    return secrets.token_urlsafe(9)


# Which kinds of things a QR tag may point at.
KINDS = ("item", "bin", "location")


class QrTag(IDMixin, TimestampMixin, db.Model):
    """A scannable code that resolves to an item, bin, or location.

    Multiple QR tags may point at the same target, so you can stick several
    printed codes on one physical bin/shelf/item.
    """

    __tablename__ = "qr_tags"

    token: Mapped[str] = mapped_column(
        String(64), unique=True, index=True, default=gen_token
    )
    description: Mapped[str] = mapped_column(String(255), default="")
    kind: Mapped[str] = mapped_column(String(16))

    # "generated": HomeHoard created and prints the QR; ``code`` == ``token``.
    # "external":  the user's own pre-existing QR/barcode; ``code`` holds the
    #              raw scanned value (e.g. a UPC/EAN number or QR payload).
    source: Mapped[str] = mapped_column(String(16), default="generated")
    # The value physically encoded on the label. For generated tags this is the
    # scan URL's token; for external tags it's whatever the user's code contains.
    code: Mapped[str] = mapped_column(String(512), default="", index=True)
    # Display hint: qr | barcode | ean13 | upc | code128 | custom | ...
    code_format: Mapped[str] = mapped_column(String(24), default="qr")

    group_id: Mapped[str] = mapped_column(String(36), ForeignKey("groups.id"))
    group = relationship("Group", back_populates="qr_tags")

    # Exactly one of the following is set, matching ``kind``.
    item_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("items.id", ondelete="CASCADE"), nullable=True
    )
    bin_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("bins.id", ondelete="CASCADE"), nullable=True
    )
    location_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("locations.id", ondelete="CASCADE"), nullable=True
    )

    item = relationship("Item")
    bin = relationship("Bin")
    location = relationship("Location")

    @property
    def target_id(self) -> str:
        return {"item": self.item_id, "bin": self.bin_id,
                "location": self.location_id}.get(self.kind)

    @property
    def target(self):
        return {"item": self.item, "bin": self.bin,
                "location": self.location}.get(self.kind)

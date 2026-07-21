from datetime import datetime

from sqlalchemy import String, Text, Boolean, Float, Integer, DateTime, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..extensions import db
from .base import IDMixin, TimestampMixin
from .label import item_labels


class Item(IDMixin, TimestampMixin, db.Model):
    __tablename__ = "items"

    name: Mapped[str] = mapped_column(String(255), index=True)
    description: Mapped[str] = mapped_column(Text, default="")
    notes: Mapped[str] = mapped_column(Text, default="")
    # quantity is a float to match homebox (supports fractional/bulk quantities)
    quantity: Mapped[float] = mapped_column(Float, default=1)
    insured: Mapped[bool] = mapped_column(Boolean, default=False)
    archived: Mapped[bool] = mapped_column(Boolean, default=False)
    # When set, moving this item's container moves its children with it.
    sync_child_locations: Mapped[bool] = mapped_column(Boolean, default=False)

    # asset id is an incrementing per-group human friendly id (e.g. 000-001)
    asset_id: Mapped[int] = mapped_column(Integer, default=0)
    import_ref: Mapped[str] = mapped_column(String(100), default="")

    # Identification
    serial_number: Mapped[str] = mapped_column(String(255), default="")
    model_number: Mapped[str] = mapped_column(String(255), default="")
    manufacturer: Mapped[str] = mapped_column(String(255), default="")

    # Purchase
    purchase_price: Mapped[float] = mapped_column(Float, default=0.0)
    purchase_from: Mapped[str] = mapped_column(String(255), default="")
    purchase_date: Mapped[datetime] = mapped_column(DateTime, nullable=True)

    # Sold
    sold_price: Mapped[float] = mapped_column(Float, default=0.0)
    sold_to: Mapped[str] = mapped_column(String(255), default="")
    sold_date: Mapped[datetime] = mapped_column(DateTime, nullable=True)
    sold_notes: Mapped[str] = mapped_column(Text, default="")

    # Warranty
    lifetime_warranty: Mapped[bool] = mapped_column(Boolean, default=False)
    warranty_expires: Mapped[datetime] = mapped_column(DateTime, nullable=True)
    warranty_details: Mapped[str] = mapped_column(Text, default="")

    # Checked in/out — "yes it's here" (False) vs "no, it's out" (True).
    checked_out: Mapped[bool] = mapped_column(Boolean, default=False)
    checked_out_to: Mapped[str] = mapped_column(String(255), default="")
    checked_out_at: Mapped[datetime] = mapped_column(DateTime, nullable=True)
    checkout_due: Mapped[datetime] = mapped_column(DateTime, nullable=True)

    # Relations
    group_id: Mapped[str] = mapped_column(String(36), ForeignKey("groups.id"))
    group = relationship("Group", back_populates="items")

    location_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("locations.id"), nullable=True
    )
    location = relationship("Location", back_populates="items")

    # An item may live directly in a location or inside a bin (which is in a
    # location). Bins are containers holding a collection of items.
    bin_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("bins.id"), nullable=True
    )
    bin = relationship("Bin", back_populates="items")

    parent_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("items.id"), nullable=True
    )
    parent = relationship("Item", remote_side="Item.id", back_populates="children")
    children = relationship("Item", back_populates="parent")

    labels = relationship("Label", secondary=item_labels, back_populates="items")
    fields = relationship(
        "ItemField", back_populates="item", cascade="all, delete-orphan"
    )
    # Per-placement quantities. `quantity` above is the SUM of these; `location`/
    # `bin` above mirror the primary (largest) holding — both kept in sync so
    # existing single-placement reads keep working. See services/holdings.py.
    holdings = relationship(
        "ItemHolding", back_populates="item", cascade="all, delete-orphan"
    )
    attachments = relationship(
        "Attachment", back_populates="item", cascade="all, delete-orphan"
    )
    maintenance_entries = relationship(
        "MaintenanceEntry", back_populates="item", cascade="all, delete-orphan"
    )
    checkout_entries = relationship(
        "CheckoutEntry", back_populates="item", cascade="all, delete-orphan"
    )


class ItemField(IDMixin, TimestampMixin, db.Model):
    __tablename__ = "item_fields"

    name: Mapped[str] = mapped_column(String(255))
    # one of: text | number | boolean | time  (matches homebox EntityField)
    type: Mapped[str] = mapped_column(String(50), default="text")
    text_value: Mapped[str] = mapped_column(Text, default="")
    number_value: Mapped[int] = mapped_column(Integer, default=0)
    boolean_value: Mapped[bool] = mapped_column(Boolean, default=False)
    time_value: Mapped[datetime] = mapped_column(DateTime, nullable=True)

    item_id: Mapped[str] = mapped_column(String(36), ForeignKey("items.id"))
    item = relationship("Item", back_populates="fields")


class ItemHolding(IDMixin, TimestampMixin, db.Model):
    """One placement of an item: a quantity in a specific bin/location. An item's
    total quantity is the sum of its holdings; item.location/bin mirror the
    primary (largest) holding for backward compatibility."""

    __tablename__ = "item_holdings"

    quantity: Mapped[float] = mapped_column(Float, default=1)
    notes: Mapped[str] = mapped_column(String(255), default="")

    item_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("items.id"), index=True
    )
    item = relationship("Item", back_populates="holdings")

    location_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("locations.id"), nullable=True
    )
    location = relationship("Location", back_populates="holdings")
    bin_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("bins.id"), nullable=True
    )
    bin = relationship("Bin", back_populates="holdings")

    group_id: Mapped[str] = mapped_column(String(36), ForeignKey("groups.id"))

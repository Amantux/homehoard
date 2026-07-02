"""Seed the database with demo data.

Usage: ``python seed.py``  (respects HBOX_* env vars)
"""
from datetime import datetime, timedelta

from app import create_app
from app.extensions import db
from app.models import (
    Group, User, Location, Label, Item, ItemField, MaintenanceEntry, Bin, QrTag,
)
from app.auth import hash_password


def run():
    app = create_app()
    with app.app_context():
        # When auth is disabled (Home Assistant mode), seed into the default
        # local group so the data is visible without logging in. Otherwise
        # create a dedicated demo group + login.
        if app.config["DISABLE_AUTH"]:
            from app.auth import _default_user

            group = _default_user().group
            if group.locations or group.items:
                print("Default group already has data; skipping seed.")
                return
            print("Seeding into the no-auth default group (no login required).")
        else:
            if db.session.query(Group).first():
                print("Database already has data; skipping seed.")
                return
            group = Group(name="Demo Home", currency="usd")
            db.session.add(group)
            db.session.flush()
            db.session.add(
                User(
                    name="Demo User",
                    email="demo@shelfie.local",
                    password_hash=hash_password("demodemo"),
                    is_owner=True,
                    group_id=group.id,
                )
            )

        garage = Location(name="Garage", group_id=group.id)
        office = Location(name="Office", group_id=group.id)
        db.session.add_all([garage, office])
        db.session.flush()
        shelf = Location(name="Tool Shelf", parent_id=garage.id, group_id=group.id)
        db.session.add(shelf)

        tools = Label(name="Tools", color="#e6a817", group_id=group.id)
        electronics = Label(name="Electronics", color="#5b8def", group_id=group.id)
        db.session.add_all([tools, electronics])
        db.session.flush()

        # A bin lives in a location and holds a collection of items.
        parts_bin = Bin(
            name="Screws & Fasteners",
            description="Assorted hardware",
            location_id=shelf.id,
            group_id=group.id,
        )
        db.session.add(parts_bin)
        db.session.flush()

        db.session.add(
            Item(
                name="M4 Screws",
                description="Box of M4 machine screws",
                quantity=200,
                asset_id=3,
                group_id=group.id,
                location_id=shelf.id,
                bin_id=parts_bin.id,
            )
        )

        drill = Item(
            name="Cordless Drill",
            description="18V brushless drill",
            manufacturer="DeWalt",
            model_number="DCD777",
            purchase_price=99.0,
            purchase_from="Home Depot",
            purchase_date=datetime.utcnow() - timedelta(days=200),
            quantity=1,
            asset_id=1,
            group_id=group.id,
            location_id=shelf.id,
        )
        drill.labels = [tools]
        drill.fields = [ItemField(name="Voltage", text_value="18V")]

        laptop = Item(
            name="Laptop",
            description="Work laptop",
            manufacturer="Lenovo",
            model_number="X1 Carbon",
            serial_number="PF-123456",
            purchase_price=1450.0,
            warranty_expires=datetime.utcnow() + timedelta(days=365),
            quantity=1,
            asset_id=2,
            insured=True,
            group_id=group.id,
            location_id=office.id,
        )
        laptop.labels = [electronics]

        db.session.add_all([drill, laptop])
        db.session.flush()
        db.session.add(
            MaintenanceEntry(
                name="Battery replacement",
                cost=25.0,
                completed_date=datetime.utcnow() - timedelta(days=30),
                item_id=drill.id,
            )
        )

        # Demo QR tags: two on the bin, one on the drill, one on a location.
        db.session.add_all(
            [
                QrTag(kind="bin", bin_id=parts_bin.id, description="lid",
                      group_id=group.id),
                QrTag(kind="bin", bin_id=parts_bin.id, description="side",
                      group_id=group.id),
                QrTag(kind="item", item_id=drill.id, group_id=group.id),
                QrTag(kind="location", location_id=garage.id, group_id=group.id),
            ]
        )
        db.session.commit()
        print("Seeded demo data (login: demo@shelfie.local / demodemo)")


if __name__ == "__main__":
    run()

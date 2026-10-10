"""Common model mixins."""
import uuid
from datetime import datetime

from sqlalchemy import String, DateTime, Numeric
from sqlalchemy.orm import Mapped, mapped_column

# Aware UTC "now"; SQLAlchemy drops the tzinfo when writing these naive
# DateTime columns, so storage stays naive UTC. Re-exported for existing importers.
from ..timeutil import utcnow  # noqa: F401


# Money is Numeric, never Float — one definition so every price column agrees.
# 12,2 comfortably covers a household item and leaves room for a currency with
# no decimal subunit being stored as whole numbers.
MONEY = Numeric(12, 2)


def gen_uuid() -> str:
    return str(uuid.uuid4())


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=utcnow, onupdate=utcnow
    )


class IDMixin:
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=gen_uuid)

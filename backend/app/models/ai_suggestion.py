from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..extensions import db
from .base import IDMixin, TimestampMixin


class AiSuggestion(IDMixin, TimestampMixin, db.Model):
    """A proposal from an AI tooling job (categorize/cluster) awaiting review, and —
    once resolved — a training example fed back as few-shot context to later runs.

    - ``categorize``: propose ``label`` for a single ``item`` (item_id set).
    - ``cluster``: propose a named grouping ``label`` over items listed in ``payload``
      (item_id null).

    High-confidence categorize proposals are auto-applied and stored as ``accepted``;
    everything else starts ``pending`` for the review queue.
    """

    __tablename__ = "ai_suggestions"

    kind: Mapped[str] = mapped_column(String(16), index=True)   # categorize | cluster
    status: Mapped[str] = mapped_column(String(16), default="pending", index=True)
    label: Mapped[str] = mapped_column(String(255))
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    rationale: Mapped[str] = mapped_column(Text, default="")
    payload: Mapped[str] = mapped_column(Text, default="")       # JSON (cluster members)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    # Cascade-delete a suggestion when its item is deleted — otherwise every
    # auto-categorized item (which gets an accepted suggestion) can't be deleted.
    item_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("items.id", ondelete="CASCADE"), nullable=True, index=True)
    item = relationship("Item")

    group_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("groups.id"), index=True)
    group = relationship("Group", back_populates="ai_suggestions")

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..extensions import db
from .base import IDMixin, TimestampMixin

_ACTIVE = "status IN ('pending','running')"


class Job(IDMixin, TimestampMixin, db.Model):
    """A background task (e.g. bulk AI enrichment), claimed and run by the worker
    poller. Group-scoped; progress is (done / total); result is a JSON summary."""

    __tablename__ = "jobs"
    # At most one ACTIVE (pending|running) job per group+kind — makes the enqueue
    # dedup a hard constraint, not a check-then-insert race.
    __table_args__ = (
        Index("uq_jobs_active_per_group_kind", "group_id", "kind", unique=True,
              sqlite_where=text(_ACTIVE), postgresql_where=text(_ACTIVE)),
    )

    kind: Mapped[str] = mapped_column(String(32), index=True)
    # pending -> running -> done | error
    status: Mapped[str] = mapped_column(String(16), default="pending", index=True)
    total: Mapped[int] = mapped_column(Integer, default=0)
    done: Mapped[int] = mapped_column(Integer, default=0)
    result: Mapped[str] = mapped_column(Text, default="")   # JSON summary when done
    error: Mapped[str] = mapped_column(Text, default="")
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    group_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("groups.id"), index=True)
    group = relationship("Group", back_populates="jobs")

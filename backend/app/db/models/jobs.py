"""Background jobs. The client polls ``GET /jobs/{job_id}``."""

from __future__ import annotations

import uuid
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.enums import JobStatus
from app.db.models._common import TIMESTAMPTZ, created_at_column, enum_type, uuid_pk


class Job(Base):
    __tablename__ = "jobs"
    __table_args__ = (
        sa.CheckConstraint("progress >= 0 AND progress <= 1", name="progress_range"),
        sa.Index("ix_jobs_case_id", "case_id"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    kind: Mapped[str] = mapped_column(sa.String(64))  # e.g. "document_processing"
    # NULL for jobs that belong to no case.
    case_id: Mapped[uuid.UUID | None] = mapped_column(
        sa.ForeignKey("cases.id", ondelete="CASCADE"), nullable=True
    )
    status: Mapped[JobStatus] = mapped_column(
        enum_type(JobStatus, "status"),
        default=JobStatus.QUEUED,
        server_default=JobStatus.QUEUED.value,
    )
    progress: Mapped[float] = mapped_column(sa.Float, default=0.0, server_default="0")
    stage: Mapped[str | None] = mapped_column(sa.String(64), nullable=True)
    error: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    created_at: Mapped[datetime] = created_at_column()
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMPTZ, server_default=sa.func.now(), onupdate=sa.func.now()
    )

"""Hardship profiles: a letter read into reason, onset, duration and intent (Feature Design 7.5).

docs/database-schema.md, section 3 (``hardship_profiles``, due D5 so the v0.5 demo shows the letter
profile). A profile is what the borrower says, not a judgement. Every item keeps the quote and the
line IDs it came from (CLAUDE.md rule 2) and whether code found the quote in those lines; a person
confirms or corrects the items later, and a correction keeps the original beside it (rule 6).

Beyond the doc's columns: ``document_id`` (a line ID such as ``p1-L6`` is only unique within a
document, so the profile names the letter), ``enclosed_documents`` (part of the profile the model
returns) and ``source`` (a model's reading, or the seeded sample the demo starts from).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.enums import HardshipSource
from app.db.models._common import TIMESTAMPTZ, created_at_column, enum_type, uuid_pk


class HardshipProfile(Base):
    __tablename__ = "hardship_profiles"
    __table_args__ = (
        # One profile per run; "latest" is the newest run (an analysis_runs row, feature hardship).
        sa.UniqueConstraint("run_id", name="uq_hardship_profiles_run_id"),
        sa.Index("ix_hardship_profiles_case_id", "case_id"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    run_id: Mapped[uuid.UUID] = mapped_column(sa.ForeignKey("analysis_runs.id", ondelete="CASCADE"))
    case_id: Mapped[uuid.UUID] = mapped_column(sa.ForeignKey("cases.id", ondelete="CASCADE"))
    # The letter the line IDs belong to. Kept if the profile outlives the file.
    document_id: Mapped[uuid.UUID | None] = mapped_column(
        sa.ForeignKey("documents.id", ondelete="SET NULL"), nullable=True
    )
    # Each of these holds the profile item as read: {"quote", "lines", ...its own fields...} plus
    # "verified" and "check_flags", which code adds after checking the quote against the lines.
    primary_reason: Mapped[dict[str, Any]] = mapped_column(JSONB)
    reasons: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, default=list, server_default=sa.text("'[]'::jsonb")
    )  # the other reasons
    onset: Mapped[dict[str, Any]] = mapped_column(JSONB)
    duration: Mapped[dict[str, Any]] = mapped_column(JSONB)
    intent: Mapped[dict[str, Any]] = mapped_column(JSONB)
    timeline: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, default=list, server_default=sa.text("'[]'::jsonb")
    )
    enclosed_documents: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, default=list, server_default=sa.text("'[]'::jsonb")
    )
    source: Mapped[HardshipSource] = mapped_column(
        enum_type(HardshipSource, "source"),
        default=HardshipSource.MODEL,
        server_default=HardshipSource.MODEL.value,
    )
    confirmed_by: Mapped[uuid.UUID | None] = mapped_column(sa.ForeignKey("users.id"), nullable=True)
    confirmed_at: Mapped[datetime | None] = mapped_column(TIMESTAMPTZ, nullable=True)
    created_at: Mapped[datetime] = created_at_column()

"""Extraction runs and the fields they produce (CPS-08 evidence, CPS-09 human review).

A re-run creates a new run with new field rows. The old run and any corrections
made on it stay as history, so a re-run never overwrites a reviewer's work, and
exactly one run per document is active.
"""

from __future__ import annotations

import uuid
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.enums import Certainty, ReviewStatus
from app.db.models._common import TIMESTAMPTZ, created_at_column, enum_type, uuid_pk


class ExtractionRun(Base):
    __tablename__ = "extraction_runs"
    __table_args__ = (
        # Lets fields reference (run, document) together, so they cannot disagree.
        sa.UniqueConstraint("id", "document_id", name="uq_extraction_runs_id_document_id"),
        # At most one active run per document.
        sa.Index(
            "uq_extraction_runs_one_active",
            "document_id",
            unique=True,
            postgresql_where=sa.text("active"),
        ),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    document_id: Mapped[uuid.UUID] = mapped_column(
        sa.ForeignKey("documents.id", ondelete="CASCADE")
    )
    doc_type: Mapped[str] = mapped_column(sa.String(64))
    active: Mapped[bool] = mapped_column(sa.Boolean, default=False, server_default=sa.false())
    prompt_id: Mapped[str | None] = mapped_column(sa.String(100), nullable=True)
    provider: Mapped[str | None] = mapped_column(sa.String(50), nullable=True)
    model: Mapped[str | None] = mapped_column(sa.String(100), nullable=True)
    created_at: Mapped[datetime] = created_at_column()


class Field(Base):
    __tablename__ = "fields"
    __table_args__ = (
        sa.ForeignKeyConstraint(
            ["run_id", "document_id"],
            ["extraction_runs.id", "extraction_runs.document_id"],
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint("run_id", "name", name="uq_fields_run_id_name"),
        sa.CheckConstraint("name ~ '^[a-z][a-z0-9_]*$'", name="name_format"),
        sa.Index("ix_fields_document_id", "document_id"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    document_id: Mapped[uuid.UUID] = mapped_column(sa.Uuid)
    run_id: Mapped[uuid.UUID] = mapped_column(sa.Uuid)
    name: Mapped[str] = mapped_column(sa.String(100))
    value: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    # The code-normalised form of the value (amounts "2033.61", dates "2026-07-31"). Which of
    # value / normalized_value the API's Field.value reads is decided with the extraction endpoint.
    normalized_value: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    # The value as first extracted. Never changed by a correction (rule 6).
    original_value: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    certainty: Mapped[Certainty] = mapped_column(enum_type(Certainty, "certainty"))
    # Line refs such as "p1-L31", within this document. The API calls them line_ids.
    # Flags live in their own table (D3); until then the API returns an empty list.
    line_refs: Mapped[list[str]] = mapped_column(
        ARRAY(sa.Text), default=list, server_default=sa.text("'{}'")
    )
    review_status: Mapped[ReviewStatus] = mapped_column(
        enum_type(ReviewStatus, "review_status"),
        default=ReviewStatus.UNREVIEWED,
        server_default=ReviewStatus.UNREVIEWED.value,
    )
    reviewed_by: Mapped[uuid.UUID | None] = mapped_column(sa.ForeignKey("users.id"), nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(TIMESTAMPTZ, nullable=True)
    review_reason: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    # Incremented on every change; the API uses it to detect edit conflicts.
    version: Mapped[int] = mapped_column(sa.Integer, default=1, server_default="1")
    created_at: Mapped[datetime] = created_at_column()

"""Analysis runs and their results (docs/database-schema.md, sections 1 and 3; due D4).

Every analysis is an ``analysis_runs`` row; "latest" means the newest run for a case and feature.
A run records which settings versions it used (``config_versions`` holds each version once), the
calculations it made (each with its formula, inputs and working, so "Show working" has something to
show) and its results: ``income_components`` for income, ``completeness_results`` for the checklist.

Nothing is overwritten (CLAUDE.md rule 6): a person's include or exclude keeps the system's own
decision beside it, and every change also writes an ``audit_events`` row.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.enums import (
    AnalysisFeature,
    AnalysisStatus,
    CompletenessOverall,
    ConfigKind,
    ConfigLabel,
    IncomeComponentKind,
)
from app.db.models._common import TIMESTAMPTZ, created_at_column, enum_type, uuid_pk


class ConfigVersion(Base):
    """One version of one settings file, recorded the first time a run uses it."""

    __tablename__ = "config_versions"
    __table_args__ = (
        # The same file content is one row, however many runs used it.
        sa.UniqueConstraint(
            "kind", "name", "version", "content_hash", name="uq_config_versions_identity"
        ),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    kind: Mapped[ConfigKind] = mapped_column(enum_type(ConfigKind, "kind"))
    name: Mapped[str] = mapped_column(sa.String(100))
    version: Mapped[str] = mapped_column(sa.String(64))
    label: Mapped[ConfigLabel] = mapped_column(enum_type(ConfigLabel, "label"))
    source: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    # SHA-256 of the file's bytes: the version label alone cannot prove a file was not edited.
    content_hash: Mapped[str] = mapped_column(sa.String(64))
    # The newest version of its kind and name.
    active: Mapped[bool] = mapped_column(sa.Boolean, default=True, server_default=sa.true())
    created_at: Mapped[datetime] = created_at_column()


class AnalysisRun(Base):
    __tablename__ = "analysis_runs"
    __table_args__ = (
        sa.Index("ix_analysis_runs_case_feature_started", "case_id", "feature", "started_at"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    case_id: Mapped[uuid.UUID] = mapped_column(sa.ForeignKey("cases.id", ondelete="CASCADE"))
    feature: Mapped[AnalysisFeature] = mapped_column(enum_type(AnalysisFeature, "feature"))
    status: Mapped[AnalysisStatus] = mapped_column(
        enum_type(AnalysisStatus, "status"),
        default=AnalysisStatus.QUEUED,
        server_default=AnalysisStatus.QUEUED.value,
    )
    job_id: Mapped[uuid.UUID | None] = mapped_column(
        sa.ForeignKey("jobs.id", ondelete="SET NULL"), nullable=True
    )
    # {kind: {"name", "version", "label", "hash"}}: the settings this run used.
    config_versions: Mapped[dict[str, Any]] = mapped_column(
        JSONB, default=dict, server_default=sa.text("'{}'::jsonb")
    )
    # Set by the service (not now()): runs created in one transaction must still order.
    started_at: Mapped[datetime] = mapped_column(TIMESTAMPTZ, server_default=sa.func.now())
    finished_at: Mapped[datetime | None] = mapped_column(TIMESTAMPTZ, nullable=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(sa.ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = created_at_column()


class Calculation(Base):
    """One computed figure with its working (rule 1: code does all arithmetic)."""

    __tablename__ = "calculations"
    __table_args__ = (sa.Index("ix_calculations_run_id", "run_id"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    run_id: Mapped[uuid.UUID] = mapped_column(sa.ForeignKey("analysis_runs.id", ondelete="CASCADE"))
    case_id: Mapped[uuid.UUID] = mapped_column(sa.ForeignKey("cases.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(sa.String(100))
    # Exact (never a float). NUMERIC(20,6) holds money, ratios and counts without rounding early;
    # `unit` says which, and the formatters round for display.
    value: Mapped[Decimal] = mapped_column(sa.Numeric(20, 6))
    unit: Mapped[str] = mapped_column(sa.String(32))
    formula: Mapped[str] = mapped_column(sa.Text)
    inputs: Mapped[dict[str, Any]] = mapped_column(JSONB)
    working: Mapped[str] = mapped_column(sa.Text)
    # Where each input came from: [{"document_id", "field", "line_ids"}] (rule 2).
    evidence: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = created_at_column()


class IncomeComponent(Base):
    __tablename__ = "income_components"
    __table_args__ = (
        # Excluding a component always carries its reason (Feature Design 2.2 step 4).
        sa.CheckConstraint("included OR exclusion_reason IS NOT NULL", name="excluded_has_reason"),
        sa.Index("ix_income_components_run_id", "run_id"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    run_id: Mapped[uuid.UUID] = mapped_column(sa.ForeignKey("analysis_runs.id", ondelete="CASCADE"))
    borrower: Mapped[str] = mapped_column(sa.Text)
    employer: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    component: Mapped[IncomeComponentKind] = mapped_column(
        enum_type(IncomeComponentKind, "component")
    )
    current_period: Mapped[Decimal | None] = mapped_column(sa.Numeric(14, 2), nullable=True)
    ytd: Mapped[Decimal | None] = mapped_column(sa.Numeric(14, 2), nullable=True)
    monthly: Mapped[Decimal] = mapped_column(sa.Numeric(14, 2))
    included: Mapped[bool] = mapped_column(sa.Boolean)
    exclusion_reason: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    # What the system decided, kept when a person changes `included` (rule 6). Not in the schema
    # doc: the doc has no place for "the original", so these two columns carry it.
    original_included: Mapped[bool] = mapped_column(sa.Boolean)
    original_exclusion_reason: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    # A person's reason for including or excluding (NULL until someone does), with updated_by/at.
    review_reason: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    calculation_id: Mapped[uuid.UUID | None] = mapped_column(
        sa.ForeignKey("calculations.id", ondelete="SET NULL"), nullable=True
    )
    updated_by: Mapped[uuid.UUID | None] = mapped_column(sa.ForeignKey("users.id"), nullable=True)
    updated_at: Mapped[datetime | None] = mapped_column(TIMESTAMPTZ, nullable=True)
    created_at: Mapped[datetime] = created_at_column()


class CompletenessResult(Base):
    __tablename__ = "completeness_results"
    __table_args__ = (
        sa.UniqueConstraint("run_id", name="uq_completeness_results_run_id"),
        sa.Index("ix_completeness_results_case_id", "case_id"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    run_id: Mapped[uuid.UUID] = mapped_column(sa.ForeignKey("analysis_runs.id", ondelete="CASCADE"))
    case_id: Mapped[uuid.UUID] = mapped_column(sa.ForeignKey("cases.id", ondelete="CASCADE"))
    # [{"item_id", "label", "status", "reason", "document_ids", "override"}]. `status` is what code
    # computed (satisfied, needs_review, partial, missing); a person's override sits beside it as
    # {"reason", "by", "at"} and never replaces it.
    items: Mapped[list[dict[str, Any]]] = mapped_column(JSONB)
    overall_status: Mapped[CompletenessOverall] = mapped_column(
        enum_type(CompletenessOverall, "overall_status")
    )
    updated_by: Mapped[uuid.UUID | None] = mapped_column(sa.ForeignKey("users.id"), nullable=True)
    updated_at: Mapped[datetime | None] = mapped_column(TIMESTAMPTZ, nullable=True)
    created_at: Mapped[datetime] = created_at_column()

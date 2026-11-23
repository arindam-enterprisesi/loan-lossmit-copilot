"""Reports, findings, conditions, sign-offs and agent runs (docs/database-schema.md, section 4).

A report is a draft written by the agents (or the seeded sample). Its findings each carry their
evidence; its suggested conditions keep the text the agents wrote beside the reviewer's edit; and a
sign-off records that a person reviewed a version of it. None of this is a decision (rule 3), and
nothing a person changes overwrites what was there (rule 6): every action also writes an
``audit_events`` row.

Arindam owns the shape of ``reports`` and ``agent_runs`` (his agents write them); Abhay owns the
migration.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.enums import (
    AgentName,
    AgentRunStatus,
    ConditionDecision,
    ConditionSource,
    ReportKind,
    ReportSource,
    ReportStatus,
    ReviewPriority,
)
from app.db.models._common import TIMESTAMPTZ, created_at_column, enum_type, uuid_pk


class Report(Base):
    __tablename__ = "reports"
    __table_args__ = (
        sa.UniqueConstraint("run_id", "version", name="uq_reports_run_id_version"),
        sa.CheckConstraint("version >= 1", name="version_positive"),
        sa.Index("ix_reports_case_id", "case_id"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    run_id: Mapped[uuid.UUID] = mapped_column(sa.ForeignKey("analysis_runs.id", ondelete="CASCADE"))
    case_id: Mapped[uuid.UUID] = mapped_column(sa.ForeignKey("cases.id", ondelete="CASCADE"))
    kind: Mapped[ReportKind] = mapped_column(enum_type(ReportKind, "kind"))
    # A re-run of an agent writes a new version of the report; sign-offs name the version reviewed.
    version: Mapped[int] = mapped_column(sa.Integer, default=1, server_default="1")
    sections: Mapped[dict[str, Any]] = mapped_column(
        JSONB, default=dict, server_default=sa.text("'{}'::jsonb")
    )
    guardrail_results: Mapped[dict[str, Any]] = mapped_column(
        JSONB, default=dict, server_default=sa.text("'{}'::jsonb")
    )
    status: Mapped[ReportStatus] = mapped_column(
        enum_type(ReportStatus, "status"),
        default=ReportStatus.DRAFT,
        server_default=ReportStatus.DRAFT.value,
    )
    # Not in the schema doc: tells a seeded sample from an agent's draft, so the demo never passes
    # one off as the other.
    source: Mapped[ReportSource] = mapped_column(
        enum_type(ReportSource, "source"),
        default=ReportSource.AGENTS,
        server_default=ReportSource.AGENTS.value,
    )
    created_at: Mapped[datetime] = created_at_column()


class Finding(Base):
    __tablename__ = "findings"
    __table_args__ = (sa.Index("ix_findings_report_id", "report_id"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    report_id: Mapped[uuid.UUID] = mapped_column(sa.ForeignKey("reports.id", ondelete="CASCADE"))
    priority: Mapped[ReviewPriority] = mapped_column(enum_type(ReviewPriority, "priority"))
    title: Mapped[str] = mapped_column(sa.Text)
    detail: Mapped[str] = mapped_column(sa.Text)
    # Where it came from (document line IDs, calculation IDs, rule IDs): rule 2.
    evidence: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONB, nullable=True)
    flag_id: Mapped[uuid.UUID | None] = mapped_column(
        sa.ForeignKey("flags.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = created_at_column()


class Condition(Base):
    """A suggested condition and what the reviewer did with it."""

    __tablename__ = "conditions"
    __table_args__ = (
        # A decision has a person and a time behind it.
        sa.CheckConstraint(
            "decision = 'pending' OR (decided_by IS NOT NULL AND decided_at IS NOT NULL)",
            name="decision_has_who_and_when",
        ),
        sa.CheckConstraint("decision <> 'edited' OR edited_text IS NOT NULL", name="edit_has_text"),
        # Editing or rejecting always carries the reviewer's reason.
        sa.CheckConstraint(
            "decision NOT IN ('edited', 'rejected') OR reason IS NOT NULL",
            name="edit_or_reject_has_reason",
        ),
        sa.Index("ix_conditions_report_id", "report_id"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    report_id: Mapped[uuid.UUID] = mapped_column(sa.ForeignKey("reports.id", ondelete="CASCADE"))
    # Display order within the report (the agents' order, then the reviewer's own additions).
    position: Mapped[int] = mapped_column(sa.Integer, default=0, server_default="0")
    # The text as the agents (or the reviewer, for their own) wrote it. Never changed.
    text: Mapped[str] = mapped_column(sa.Text)
    priority: Mapped[ReviewPriority] = mapped_column(enum_type(ReviewPriority, "priority"))
    source: Mapped[ConditionSource] = mapped_column(enum_type(ConditionSource, "source"))
    decision: Mapped[ConditionDecision] = mapped_column(
        enum_type(ConditionDecision, "decision"),
        default=ConditionDecision.PENDING,
        server_default=ConditionDecision.PENDING.value,
    )
    edited_text: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    reason: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    decided_by: Mapped[uuid.UUID | None] = mapped_column(sa.ForeignKey("users.id"), nullable=True)
    decided_at: Mapped[datetime | None] = mapped_column(TIMESTAMPTZ, nullable=True)
    created_at: Mapped[datetime] = created_at_column()


class SignOff(Base):
    """A record that a person reviewed a version of a report. It is never a decision."""

    __tablename__ = "sign_offs"
    __table_args__ = (
        sa.CheckConstraint("report_version >= 1", name="report_version_positive"),
        sa.CheckConstraint(
            "role IN ('underwriter', 'lm_specialist', 'admin')", name="role_is_a_role"
        ),
        sa.Index("ix_sign_offs_report_id", "report_id"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    report_id: Mapped[uuid.UUID] = mapped_column(sa.ForeignKey("reports.id", ondelete="CASCADE"))
    case_id: Mapped[uuid.UUID] = mapped_column(sa.ForeignKey("cases.id", ondelete="CASCADE"))
    # Not in the schema doc: which version of the report the person reviewed.
    report_version: Mapped[int] = mapped_column(sa.Integer)
    signed_by: Mapped[uuid.UUID] = mapped_column(sa.ForeignKey("users.id"))
    role: Mapped[str] = mapped_column(sa.String(32))
    signed_at: Mapped[datetime] = mapped_column(TIMESTAMPTZ, server_default=sa.func.now())
    note: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    created_at: Mapped[datetime] = created_at_column()


class AgentRun(Base):
    """One attempt of the Researcher, Writer or Critic."""

    __tablename__ = "agent_runs"
    __table_args__ = (
        sa.UniqueConstraint(
            "run_id", "agent", "attempt", name="uq_agent_runs_run_id_agent_attempt"
        ),
        sa.CheckConstraint("attempt >= 1", name="attempt_positive"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    run_id: Mapped[uuid.UUID] = mapped_column(sa.ForeignKey("analysis_runs.id", ondelete="CASCADE"))
    agent: Mapped[AgentName] = mapped_column(enum_type(AgentName, "agent"))
    attempt: Mapped[int] = mapped_column(sa.Integer, default=1, server_default="1")
    status: Mapped[AgentRunStatus] = mapped_column(enum_type(AgentRunStatus, "status"))
    provider: Mapped[str | None] = mapped_column(sa.String(32), nullable=True)
    model: Mapped[str | None] = mapped_column(sa.String(100), nullable=True)
    prompt_id: Mapped[str | None] = mapped_column(sa.String(100), nullable=True)
    output: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    error: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(TIMESTAMPTZ, nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(TIMESTAMPTZ, nullable=True)
    created_at: Mapped[datetime] = created_at_column()

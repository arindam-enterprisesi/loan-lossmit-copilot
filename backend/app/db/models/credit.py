"""Tables for the credit report analysis (docs/database-schema.md, Feature 4; D7).

The sample credit report is read through the document pipeline into fields; a run of the analysis
copies what the report says into these tables (with the lines each came from, so every figure and
flag links back to evidence) and stores the metrics as ``calculations`` and the risks as ``flags``.
Nothing here is a bureau's data: the report is simulated.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.models._common import created_at_column, uuid_pk

MONEY = sa.Numeric(14, 2)


class CreditScore(Base):
    __tablename__ = "credit_scores"
    __table_args__ = (
        sa.CheckConstraint("score BETWEEN 300 AND 850", name="score_in_range"),
        sa.Index("ix_credit_scores_run_id", "run_id"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    run_id: Mapped[uuid.UUID] = mapped_column(sa.ForeignKey("analysis_runs.id", ondelete="CASCADE"))
    case_id: Mapped[uuid.UUID] = mapped_column(sa.ForeignKey("cases.id", ondelete="CASCADE"))
    document_id: Mapped[uuid.UUID | None] = mapped_column(
        sa.ForeignKey("documents.id", ondelete="SET NULL"), nullable=True
    )
    bureau: Mapped[str] = mapped_column(sa.String(64))
    score: Mapped[int] = mapped_column(sa.Integer)
    is_representative: Mapped[bool] = mapped_column(
        sa.Boolean, default=False, server_default=sa.false()
    )
    line_refs: Mapped[list[str]] = mapped_column(
        ARRAY(sa.Text), default=list, server_default=sa.text("'{}'")
    )
    created_at: Mapped[datetime] = created_at_column()


class Tradeline(Base):
    __tablename__ = "tradelines"
    __table_args__ = (
        sa.CheckConstraint(
            "late_30 >= 0 AND late_60 >= 0 AND late_90 >= 0", name="late_counts_non_negative"
        ),
        sa.UniqueConstraint("run_id", "position", name="uq_tradelines_run_id_position"),
        sa.Index("ix_tradelines_run_id", "run_id"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    run_id: Mapped[uuid.UUID] = mapped_column(sa.ForeignKey("analysis_runs.id", ondelete="CASCADE"))
    case_id: Mapped[uuid.UUID] = mapped_column(sa.ForeignKey("cases.id", ondelete="CASCADE"))
    document_id: Mapped[uuid.UUID | None] = mapped_column(
        sa.ForeignKey("documents.id", ondelete="SET NULL"), nullable=True
    )
    # The row's place on the report (the ``NNN`` of ``tradeline_NNN_creditor``).
    position: Mapped[int] = mapped_column(sa.Integer)
    creditor: Mapped[str] = mapped_column(sa.Text)
    account_type: Mapped[str] = mapped_column(sa.String(32))
    ownership: Mapped[str | None] = mapped_column(sa.String(32), nullable=True)
    opened_on: Mapped[date | None] = mapped_column(sa.Date, nullable=True)
    status: Mapped[str | None] = mapped_column(sa.String(64), nullable=True)
    balance: Mapped[Decimal | None] = mapped_column(MONEY, nullable=True)
    credit_limit: Mapped[Decimal | None] = mapped_column(MONEY, nullable=True)
    monthly_payment: Mapped[Decimal | None] = mapped_column(MONEY, nullable=True)
    past_due: Mapped[Decimal | None] = mapped_column(MONEY, nullable=True)
    late_30: Mapped[int] = mapped_column(sa.Integer, default=0, server_default="0")
    late_60: Mapped[int] = mapped_column(sa.Integer, default=0, server_default="0")
    late_90: Mapped[int] = mapped_column(sa.Integer, default=0, server_default="0")
    last_late_on: Mapped[date | None] = mapped_column(sa.Date, nullable=True)
    remarks: Mapped[str] = mapped_column(sa.Text, default="", server_default="")
    line_refs: Mapped[list[str]] = mapped_column(
        ARRAY(sa.Text), default=list, server_default=sa.text("'{}'")
    )
    # Metrics a person can read at a glance; the stored calculations hold the working.
    utilization_over_review_level: Mapped[bool] = mapped_column(
        sa.Boolean, default=False, server_default=sa.false()
    )
    late_in_lookback: Mapped[bool] = mapped_column(
        sa.Boolean, default=False, server_default=sa.false()
    )
    derogatory: Mapped[bool] = mapped_column(sa.Boolean, default=False, server_default=sa.false())
    created_at: Mapped[datetime] = created_at_column()


class CreditInquiry(Base):
    __tablename__ = "credit_inquiries"
    __table_args__ = (
        sa.UniqueConstraint("run_id", "position", name="uq_credit_inquiries_run_id_position"),
        sa.Index("ix_credit_inquiries_run_id", "run_id"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    run_id: Mapped[uuid.UUID] = mapped_column(sa.ForeignKey("analysis_runs.id", ondelete="CASCADE"))
    case_id: Mapped[uuid.UUID] = mapped_column(sa.ForeignKey("cases.id", ondelete="CASCADE"))
    document_id: Mapped[uuid.UUID | None] = mapped_column(
        sa.ForeignKey("documents.id", ondelete="SET NULL"), nullable=True
    )
    position: Mapped[int] = mapped_column(sa.Integer)
    creditor: Mapped[str] = mapped_column(sa.Text)
    inquired_on: Mapped[date | None] = mapped_column(sa.Date, nullable=True)
    in_window: Mapped[bool] = mapped_column(sa.Boolean, default=False, server_default=sa.false())
    matched_tradeline_id: Mapped[uuid.UUID | None] = mapped_column(
        sa.ForeignKey("tradelines.id", ondelete="SET NULL"), nullable=True
    )
    line_refs: Mapped[list[str]] = mapped_column(
        ARRAY(sa.Text), default=list, server_default=sa.text("'{}'")
    )
    created_at: Mapped[datetime] = created_at_column()

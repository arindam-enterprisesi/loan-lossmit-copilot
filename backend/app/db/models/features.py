"""Tables for the loan scenario, the servicing record, transactions, obligations and the budget.

docs/database-schema.md, sections 2 and 3 (due D6). ``loan_scenarios`` is entered by hand for a
Pillar 1 case and ``loan_records`` is a simulated servicing record for a Pillar 2 case.
``transactions`` are the labelled lines of each bank statement; ``obligations`` and ``budget_lines``
are results of a run (Feature 3 and Feature 7).

Nothing is overwritten (CLAUDE.md rule 6): where a person can change what the system decided, the
system's value stays beside theirs (``original_category``, ``original_counts_toward_dti``), with who
changed it, when and why. Every change also writes an ``audit_events`` row.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.enums import (
    CategorySource,
    LoanRecordSource,
    ObligationSource,
    TransactionCategory,
    TransactionDirection,
)
from app.db.models._common import TIMESTAMPTZ, created_at_column, enum_type, uuid_pk

MONEY = sa.Numeric(14, 2)


class LoanScenario(Base):
    """The sample loan, entered by hand. Nothing is priced (Feature Design 3.3)."""

    __tablename__ = "loan_scenarios"
    __table_args__ = (
        sa.CheckConstraint("property_value > 0", name="property_value_positive"),
        sa.CheckConstraint("loan_amount >= 0", name="loan_amount_non_negative"),
        sa.CheckConstraint(
            "proposed_housing_payment >= 0", name="proposed_housing_payment_non_negative"
        ),
        sa.CheckConstraint("funds_to_close >= 0", name="funds_to_close_non_negative"),
    )

    # Keyed by the case: a case has at most one scenario, and a new one replaces it (the old values
    # go in the audit event).
    case_id: Mapped[uuid.UUID] = mapped_column(
        sa.ForeignKey("cases.id", ondelete="CASCADE"), primary_key=True
    )
    purpose: Mapped[str] = mapped_column(sa.String(64))
    occupancy: Mapped[str] = mapped_column(sa.String(64))
    property_value: Mapped[Decimal] = mapped_column(MONEY)
    loan_amount: Mapped[Decimal] = mapped_column(MONEY)
    proposed_housing_payment: Mapped[Decimal] = mapped_column(MONEY)
    funds_to_close: Mapped[Decimal] = mapped_column(MONEY)
    created_by: Mapped[uuid.UUID | None] = mapped_column(sa.ForeignKey("users.id"), nullable=True)
    updated_by: Mapped[uuid.UUID | None] = mapped_column(sa.ForeignKey("users.id"), nullable=True)
    updated_at: Mapped[datetime | None] = mapped_column(TIMESTAMPTZ, nullable=True)
    created_at: Mapped[datetime] = created_at_column()


class LoanRecord(Base):
    """The simulated servicing record of a loss-mitigation case (Feature Design 7.3)."""

    __tablename__ = "loan_records"
    __table_args__ = (
        sa.UniqueConstraint("case_id", name="uq_loan_records_case_id"),
        sa.CheckConstraint("months_delinquent >= 0", name="months_delinquent_non_negative"),
        sa.CheckConstraint("arrears_amount >= 0", name="arrears_amount_non_negative"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    case_id: Mapped[uuid.UUID] = mapped_column(sa.ForeignKey("cases.id", ondelete="CASCADE"))
    loan_id: Mapped[str] = mapped_column(sa.String(64))
    investor: Mapped[str] = mapped_column(sa.Text)
    unpaid_balance: Mapped[Decimal] = mapped_column(MONEY)
    monthly_payment: Mapped[Decimal] = mapped_column(MONEY)
    principal_interest: Mapped[Decimal] = mapped_column(MONEY)
    escrow: Mapped[Decimal] = mapped_column(MONEY)
    next_due_date: Mapped[date] = mapped_column(sa.Date)
    months_delinquent: Mapped[int] = mapped_column(sa.Integer)
    arrears_amount: Mapped[Decimal] = mapped_column(MONEY)
    source: Mapped[LoanRecordSource] = mapped_column(
        enum_type(LoanRecordSource, "source"),
        default=LoanRecordSource.SYNTHETIC,
        server_default=LoanRecordSource.SYNTHETIC.value,
    )
    created_at: Mapped[datetime] = created_at_column()


class Transaction(Base):
    """One line of a bank statement, with the label it was given (Feature Design 3.5).

    Keyed by the statement and the line, not by a run: the labels are what a reviewer sees and
    changes, so a later analysis run reads them and never relabels a line a person has changed.
    """

    __tablename__ = "transactions"
    __table_args__ = (
        sa.UniqueConstraint("document_id", "line_ref", name="uq_transactions_document_id_line_ref"),
        sa.CheckConstraint("line_ref ~ '^p[0-9]+-L[0-9]+$'", name="line_ref_format"),
        sa.CheckConstraint("amount >= 0", name="amount_non_negative"),
        sa.Index("ix_transactions_document_id", "document_id"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    document_id: Mapped[uuid.UUID] = mapped_column(
        sa.ForeignKey("documents.id", ondelete="CASCADE")
    )
    line_ref: Mapped[str] = mapped_column(sa.Text)
    account_last4: Mapped[str | None] = mapped_column(sa.String(4), nullable=True)
    posted_on: Mapped[date] = mapped_column(sa.Date)
    description: Mapped[str] = mapped_column(sa.Text)
    # The size of the movement; ``direction`` says which way it went.
    amount: Mapped[Decimal] = mapped_column(MONEY)
    direction: Mapped[TransactionDirection] = mapped_column(
        enum_type(TransactionDirection, "direction")
    )
    category: Mapped[TransactionCategory] = mapped_column(
        enum_type(TransactionCategory, "category")
    )
    counterparty: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    category_source: Mapped[CategorySource] = mapped_column(
        enum_type(CategorySource, "category_source"),
        default=CategorySource.AI,
        server_default=CategorySource.AI.value,
    )
    # What the system labelled, kept when a person reclassifies the line (NULL until then).
    original_category: Mapped[TransactionCategory | None] = mapped_column(
        enum_type(TransactionCategory, "original_category"), nullable=True
    )
    # The labeller could not place it (still "other" after one retry): a person should look.
    needs_review: Mapped[bool] = mapped_column(sa.Boolean, default=False, server_default=sa.false())
    # The pay stub field this deposit was matched to, when it is a payroll deposit.
    payroll_match_field_id: Mapped[uuid.UUID | None] = mapped_column(
        sa.ForeignKey("fields.id", ondelete="SET NULL"), nullable=True
    )
    # A person marked the deposit as sourced, with a note (not verification: Feature Design 3.1).
    sourced: Mapped[bool] = mapped_column(sa.Boolean, default=False, server_default=sa.false())
    sourced_note: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    review_reason: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    updated_by: Mapped[uuid.UUID | None] = mapped_column(sa.ForeignKey("users.id"), nullable=True)
    updated_at: Mapped[datetime | None] = mapped_column(TIMESTAMPTZ, nullable=True)
    created_at: Mapped[datetime] = created_at_column()


class Obligation(Base):
    """A recurring debt found in the bank statements, the credit report or both."""

    __tablename__ = "obligations"
    __table_args__ = (
        sa.CheckConstraint("monthly_payment >= 0", name="monthly_payment_non_negative"),
        sa.Index("ix_obligations_run_id", "run_id"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    run_id: Mapped[uuid.UUID] = mapped_column(sa.ForeignKey("analysis_runs.id", ondelete="CASCADE"))
    case_id: Mapped[uuid.UUID] = mapped_column(sa.ForeignKey("cases.id", ondelete="CASCADE"))
    creditor: Mapped[str] = mapped_column(sa.Text)
    kind: Mapped[str] = mapped_column(sa.String(32))  # revolving, installment, ...
    monthly_payment: Mapped[Decimal] = mapped_column(MONEY)
    balance: Mapped[Decimal | None] = mapped_column(MONEY, nullable=True)
    source: Mapped[ObligationSource] = mapped_column(enum_type(ObligationSource, "source"))
    counts_toward_dti: Mapped[bool] = mapped_column(sa.Boolean)
    # Why it counts or does not (the system's reason; a person's own goes in ``review_reason``).
    reason: Mapped[str] = mapped_column(sa.Text)
    # What the system decided, kept when a person includes or excludes the debt (rule 6).
    original_counts_toward_dti: Mapped[bool] = mapped_column(sa.Boolean)
    review_reason: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    updated_by: Mapped[uuid.UUID | None] = mapped_column(sa.ForeignKey("users.id"), nullable=True)
    updated_at: Mapped[datetime | None] = mapped_column(TIMESTAMPTZ, nullable=True)
    created_at: Mapped[datetime] = created_at_column()


class BudgetLine(Base):
    """One category of the hardship budget on the stated and observed bases (Feature Design 7.5)."""

    __tablename__ = "budget_lines"
    __table_args__ = (
        sa.UniqueConstraint("run_id", "category", name="uq_budget_lines_run_id_category"),
        # An adjustment always carries its reason (Feature Design 7.2).
        sa.CheckConstraint(
            "adjusted_amount IS NULL OR adjustment_reason IS NOT NULL",
            name="adjustment_has_reason",
        ),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    run_id: Mapped[uuid.UUID] = mapped_column(sa.ForeignKey("analysis_runs.id", ondelete="CASCADE"))
    category: Mapped[str] = mapped_column(sa.String(64))
    stated_amount: Mapped[Decimal | None] = mapped_column(MONEY, nullable=True)
    observed_amount: Mapped[Decimal | None] = mapped_column(MONEY, nullable=True)
    adjusted_amount: Mapped[Decimal | None] = mapped_column(MONEY, nullable=True)
    adjustment_reason: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    flagged: Mapped[bool] = mapped_column(sa.Boolean, default=False, server_default=sa.false())
    updated_by: Mapped[uuid.UUID | None] = mapped_column(sa.ForeignKey("users.id"), nullable=True)
    updated_at: Mapped[datetime | None] = mapped_column(TIMESTAMPTZ, nullable=True)
    created_at: Mapped[datetime] = created_at_column()

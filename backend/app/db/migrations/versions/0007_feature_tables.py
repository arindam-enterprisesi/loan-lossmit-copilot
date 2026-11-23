"""feature tables: loan scenarios, loan records, transactions, obligations, budget lines

Revision ID: 0007
Revises: 0006
Create Date: 2026-11-23

The five tables docs/database-schema.md lists as due on D6 for Features 3 and 7.
``loan_scenarios`` is keyed by the case (one per case), as the doc says. ``transactions`` follows
the doc and is keyed by the statement and the line, not by a run.

Columns the doc does not list, all so a correction never overwrites what the system decided
(rule 6): ``transactions.original_category`` (with ``needs_review``, ``sourced``, ``review_reason``
and who and when), ``obligations.original_counts_toward_dti`` (with ``review_reason``, who and when)
and ``budget_lines.updated_by/at``; and ``loan_scenarios.created_by/updated_by/updated_at``. The
``flagged`` flag on a budget line defaults to false.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

CATEGORIES = (
    "payroll deposit",
    "other income deposit",
    "transfer in",
    "transfer out",
    "housing payment",
    "loan payment",
    "credit card payment",
    "utility",
    "insurance",
    "everyday spending",
    "overdraft or returned-item fee",
    "other fee",
    "refund",
    "other",
)


def _enum(name: str, *values: str) -> sa.Enum:
    return sa.Enum(*values, name=name, native_enum=False, create_constraint=True, length=32)


def _created_at() -> sa.Column[object]:
    return sa.Column(
        "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
    )


def _id() -> sa.Column[object]:
    return sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False)


def upgrade() -> None:
    op.create_table(
        "loan_scenarios",
        sa.Column("case_id", sa.Uuid(), nullable=False),
        sa.Column("purpose", sa.String(length=64), nullable=False),
        sa.Column("occupancy", sa.String(length=64), nullable=False),
        sa.Column("property_value", sa.Numeric(precision=14, scale=2), nullable=False),
        sa.Column("loan_amount", sa.Numeric(precision=14, scale=2), nullable=False),
        sa.Column("proposed_housing_payment", sa.Numeric(precision=14, scale=2), nullable=False),
        sa.Column("funds_to_close", sa.Numeric(precision=14, scale=2), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("updated_by", sa.Uuid(), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        _created_at(),
        sa.CheckConstraint(
            "funds_to_close >= 0", name=op.f("ck_loan_scenarios_funds_to_close_non_negative")
        ),
        sa.CheckConstraint(
            "loan_amount >= 0", name=op.f("ck_loan_scenarios_loan_amount_non_negative")
        ),
        sa.CheckConstraint(
            "proposed_housing_payment >= 0",
            name=op.f("ck_loan_scenarios_proposed_housing_payment_non_negative"),
        ),
        sa.CheckConstraint(
            "property_value > 0", name=op.f("ck_loan_scenarios_property_value_positive")
        ),
        sa.ForeignKeyConstraint(
            ["case_id"],
            ["cases.id"],
            name=op.f("fk_loan_scenarios_case_id_cases"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["created_by"], ["users.id"], name=op.f("fk_loan_scenarios_created_by_users")
        ),
        sa.ForeignKeyConstraint(
            ["updated_by"], ["users.id"], name=op.f("fk_loan_scenarios_updated_by_users")
        ),
        sa.PrimaryKeyConstraint("case_id", name=op.f("pk_loan_scenarios")),
    )

    op.create_table(
        "loan_records",
        _id(),
        sa.Column("case_id", sa.Uuid(), nullable=False),
        sa.Column("loan_id", sa.String(length=64), nullable=False),
        sa.Column("investor", sa.Text(), nullable=False),
        sa.Column("unpaid_balance", sa.Numeric(precision=14, scale=2), nullable=False),
        sa.Column("monthly_payment", sa.Numeric(precision=14, scale=2), nullable=False),
        sa.Column("principal_interest", sa.Numeric(precision=14, scale=2), nullable=False),
        sa.Column("escrow", sa.Numeric(precision=14, scale=2), nullable=False),
        sa.Column("next_due_date", sa.Date(), nullable=False),
        sa.Column("months_delinquent", sa.Integer(), nullable=False),
        sa.Column("arrears_amount", sa.Numeric(precision=14, scale=2), nullable=False),
        sa.Column(
            "source", _enum("source", "synthetic"), server_default="synthetic", nullable=False
        ),
        _created_at(),
        sa.CheckConstraint(
            "arrears_amount >= 0", name=op.f("ck_loan_records_arrears_amount_non_negative")
        ),
        sa.CheckConstraint(
            "months_delinquent >= 0", name=op.f("ck_loan_records_months_delinquent_non_negative")
        ),
        sa.ForeignKeyConstraint(
            ["case_id"],
            ["cases.id"],
            name=op.f("fk_loan_records_case_id_cases"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_loan_records")),
        sa.UniqueConstraint("case_id", name="uq_loan_records_case_id"),
    )

    op.create_table(
        "transactions",
        _id(),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("line_ref", sa.Text(), nullable=False),
        sa.Column("account_last4", sa.String(length=4), nullable=True),
        sa.Column("posted_on", sa.Date(), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("amount", sa.Numeric(precision=14, scale=2), nullable=False),
        sa.Column("direction", _enum("direction", "credit", "debit"), nullable=False),
        sa.Column("category", _enum("category", *CATEGORIES), nullable=False),
        sa.Column("counterparty", sa.Text(), nullable=True),
        sa.Column(
            "category_source",
            _enum("category_source", "ai", "user"),
            server_default="ai",
            nullable=False,
        ),
        sa.Column("original_category", _enum("original_category", *CATEGORIES), nullable=True),
        sa.Column("needs_review", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("payroll_match_field_id", sa.Uuid(), nullable=True),
        sa.Column("sourced", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("sourced_note", sa.Text(), nullable=True),
        sa.Column("review_reason", sa.Text(), nullable=True),
        sa.Column("updated_by", sa.Uuid(), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        _created_at(),
        sa.CheckConstraint("amount >= 0", name=op.f("ck_transactions_amount_non_negative")),
        sa.CheckConstraint(
            "line_ref ~ '^p[0-9]+-L[0-9]+$'", name=op.f("ck_transactions_line_ref_format")
        ),
        sa.ForeignKeyConstraint(
            ["document_id"],
            ["documents.id"],
            name=op.f("fk_transactions_document_id_documents"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["payroll_match_field_id"],
            ["fields.id"],
            name=op.f("fk_transactions_payroll_match_field_id_fields"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["updated_by"], ["users.id"], name=op.f("fk_transactions_updated_by_users")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_transactions")),
        sa.UniqueConstraint("document_id", "line_ref", name="uq_transactions_document_id_line_ref"),
    )
    op.create_index("ix_transactions_document_id", "transactions", ["document_id"], unique=False)

    op.create_table(
        "obligations",
        _id(),
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("case_id", sa.Uuid(), nullable=False),
        sa.Column("creditor", sa.Text(), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("monthly_payment", sa.Numeric(precision=14, scale=2), nullable=False),
        sa.Column("balance", sa.Numeric(precision=14, scale=2), nullable=True),
        sa.Column("source", _enum("source", "bank", "credit_report", "both"), nullable=False),
        sa.Column("counts_toward_dti", sa.Boolean(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("original_counts_toward_dti", sa.Boolean(), nullable=False),
        sa.Column("review_reason", sa.Text(), nullable=True),
        sa.Column("updated_by", sa.Uuid(), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        _created_at(),
        sa.CheckConstraint(
            "monthly_payment >= 0", name=op.f("ck_obligations_monthly_payment_non_negative")
        ),
        sa.ForeignKeyConstraint(
            ["case_id"], ["cases.id"], name=op.f("fk_obligations_case_id_cases"), ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["analysis_runs.id"],
            name=op.f("fk_obligations_run_id_analysis_runs"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["updated_by"], ["users.id"], name=op.f("fk_obligations_updated_by_users")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_obligations")),
    )
    op.create_index("ix_obligations_run_id", "obligations", ["run_id"], unique=False)

    op.create_table(
        "budget_lines",
        _id(),
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("category", sa.String(length=64), nullable=False),
        sa.Column("stated_amount", sa.Numeric(precision=14, scale=2), nullable=True),
        sa.Column("observed_amount", sa.Numeric(precision=14, scale=2), nullable=True),
        sa.Column("adjusted_amount", sa.Numeric(precision=14, scale=2), nullable=True),
        sa.Column("adjustment_reason", sa.Text(), nullable=True),
        sa.Column("flagged", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("updated_by", sa.Uuid(), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        _created_at(),
        sa.CheckConstraint(
            "adjusted_amount IS NULL OR adjustment_reason IS NOT NULL",
            name=op.f("ck_budget_lines_adjustment_has_reason"),
        ),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["analysis_runs.id"],
            name=op.f("fk_budget_lines_run_id_analysis_runs"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["updated_by"], ["users.id"], name=op.f("fk_budget_lines_updated_by_users")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_budget_lines")),
        sa.UniqueConstraint("run_id", "category", name="uq_budget_lines_run_id_category"),
    )


def downgrade() -> None:
    op.drop_table("budget_lines")
    op.drop_index("ix_obligations_run_id", table_name="obligations")
    op.drop_table("obligations")
    op.drop_index("ix_transactions_document_id", table_name="transactions")
    op.drop_table("transactions")
    op.drop_table("loan_records")
    op.drop_table("loan_scenarios")

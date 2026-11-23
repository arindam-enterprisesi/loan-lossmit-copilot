"""credit tables: credit_scores, tradelines, credit_inquiries

Revision ID: 0009
Revises: 0008
Create Date: 2026-11-24

The three tables docs/database-schema.md lists for Feature 4 (the credit report analysis), built
because the feature was kept. The guideline tables (``guideline_sources``, ``rag_chunks``,
``guideline_questions``) still wait for the embedding size and come in their own migration after
this one.

Columns the doc does not list: ``case_id`` and ``document_id`` on each table (so a figure links to
the report it came from), ``position`` (the row's place on the report, the ``NNN`` of
``tradeline_NNN_creditor``), ``line_refs`` on scores and inquiries (evidence, rule 2),
``tradelines.utilization_over_review_level`` / ``late_in_lookback`` / ``derogatory`` (what code
found, so a screen can filter without recomputing), ``credit_inquiries.in_window`` and
``created_at`` everywhere. The report is simulated; nothing here is a bureau's data.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _id() -> sa.Column[object]:
    return sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False)


def _created_at() -> sa.Column[object]:
    return sa.Column(
        "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
    )


def _line_refs() -> sa.Column[object]:
    return sa.Column(
        "line_refs", postgresql.ARRAY(sa.Text()), server_default=sa.text("'{}'"), nullable=False
    )


def _refs(table: str) -> list[sa.schema.SchemaItem]:
    return [
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["analysis_runs.id"],
            name=op.f(f"fk_{table}_run_id_analysis_runs"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["case_id"], ["cases.id"], name=op.f(f"fk_{table}_case_id_cases"), ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["document_id"],
            ["documents.id"],
            name=op.f(f"fk_{table}_document_id_documents"),
            ondelete="SET NULL",
        ),
    ]


def upgrade() -> None:
    op.create_table(
        "credit_scores",
        _id(),
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("case_id", sa.Uuid(), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=True),
        sa.Column("bureau", sa.String(length=64), nullable=False),
        sa.Column("score", sa.Integer(), nullable=False),
        sa.Column("is_representative", sa.Boolean(), server_default=sa.false(), nullable=False),
        _line_refs(),
        _created_at(),
        sa.CheckConstraint(
            "score BETWEEN 300 AND 850", name=op.f("ck_credit_scores_score_in_range")
        ),
        *_refs("credit_scores"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_credit_scores")),
    )
    op.create_index("ix_credit_scores_run_id", "credit_scores", ["run_id"], unique=False)

    op.create_table(
        "tradelines",
        _id(),
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("case_id", sa.Uuid(), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=True),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("creditor", sa.Text(), nullable=False),
        sa.Column("account_type", sa.String(length=32), nullable=False),
        sa.Column("ownership", sa.String(length=32), nullable=True),
        sa.Column("opened_on", sa.Date(), nullable=True),
        sa.Column("status", sa.String(length=64), nullable=True),
        sa.Column("balance", sa.Numeric(precision=14, scale=2), nullable=True),
        sa.Column("credit_limit", sa.Numeric(precision=14, scale=2), nullable=True),
        sa.Column("monthly_payment", sa.Numeric(precision=14, scale=2), nullable=True),
        sa.Column("past_due", sa.Numeric(precision=14, scale=2), nullable=True),
        sa.Column("late_30", sa.Integer(), server_default="0", nullable=False),
        sa.Column("late_60", sa.Integer(), server_default="0", nullable=False),
        sa.Column("late_90", sa.Integer(), server_default="0", nullable=False),
        sa.Column("last_late_on", sa.Date(), nullable=True),
        sa.Column("remarks", sa.Text(), server_default="", nullable=False),
        _line_refs(),
        sa.Column(
            "utilization_over_review_level", sa.Boolean(), server_default=sa.false(), nullable=False
        ),
        sa.Column("late_in_lookback", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("derogatory", sa.Boolean(), server_default=sa.false(), nullable=False),
        _created_at(),
        sa.CheckConstraint(
            "late_30 >= 0 AND late_60 >= 0 AND late_90 >= 0",
            name=op.f("ck_tradelines_late_counts_non_negative"),
        ),
        *_refs("tradelines"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_tradelines")),
        sa.UniqueConstraint("run_id", "position", name="uq_tradelines_run_id_position"),
    )
    op.create_index("ix_tradelines_run_id", "tradelines", ["run_id"], unique=False)

    op.create_table(
        "credit_inquiries",
        _id(),
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("case_id", sa.Uuid(), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=True),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("creditor", sa.Text(), nullable=False),
        sa.Column("inquired_on", sa.Date(), nullable=True),
        sa.Column("in_window", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("matched_tradeline_id", sa.Uuid(), nullable=True),
        _line_refs(),
        _created_at(),
        *_refs("credit_inquiries"),
        sa.ForeignKeyConstraint(
            ["matched_tradeline_id"],
            ["tradelines.id"],
            name=op.f("fk_credit_inquiries_matched_tradeline_id_tradelines"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_credit_inquiries")),
        sa.UniqueConstraint("run_id", "position", name="uq_credit_inquiries_run_id_position"),
    )
    op.create_index("ix_credit_inquiries_run_id", "credit_inquiries", ["run_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_credit_inquiries_run_id", table_name="credit_inquiries")
    op.drop_table("credit_inquiries")
    op.drop_index("ix_tradelines_run_id", table_name="tradelines")
    op.drop_table("tradelines")
    op.drop_index("ix_credit_scores_run_id", table_name="credit_scores")
    op.drop_table("credit_scores")

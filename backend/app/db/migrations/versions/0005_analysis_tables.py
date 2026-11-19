"""analysis tables

Revision ID: 0005
Revises: 0004
Create Date: 2026-11-19

The five tables docs/database-schema.md lists as due on D4: ``config_versions``, ``analysis_runs``,
``calculations``, ``income_components`` and ``completeness_results``, with the doc's columns plus
``created_at`` (the "every row" convention) and ``updated_by``/``updated_at`` where a person
changes a row.

Three columns are not in the doc, all on ``income_components``: ``original_included``,
``original_exclusion_reason`` and ``review_reason``. The doc's ``included`` and ``exclusion_reason``
are what a reviewer can change, and "corrections never overwrite" needs the system's own decision
kept beside them, and the reviewer's own reason (for including as well as excluding) kept apart
from the reason the system gave.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "config_versions",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column(
            "kind",
            sa.Enum(
                "checklist",
                "income_method",
                "thresholds",
                "rule_set",
                "llm",
                "templates",
                name="kind",
                native_enum=False,
                create_constraint=True,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("version", sa.String(length=64), nullable=False),
        sa.Column(
            "label",
            sa.Enum(
                "illustrative",
                "authoritative",
                name="label",
                native_enum=False,
                create_constraint=True,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column("source", sa.Text(), nullable=True),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_config_versions")),
        sa.UniqueConstraint(
            "kind", "name", "version", "content_hash", name="uq_config_versions_identity"
        ),
    )
    op.create_table(
        "analysis_runs",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("case_id", sa.Uuid(), nullable=False),
        sa.Column(
            "feature",
            sa.Enum(
                "income",
                "assets",
                "credit",
                "hardship",
                "underwriting",
                "lm_recommendation",
                "completeness",
                name="feature",
                native_enum=False,
                create_constraint=True,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column(
            "status",
            sa.Enum(
                "queued",
                "running",
                "succeeded",
                "failed",
                name="status",
                native_enum=False,
                create_constraint=True,
                length=32,
            ),
            server_default="queued",
            nullable=False,
        ),
        sa.Column("job_id", sa.Uuid(), nullable=True),
        sa.Column(
            "config_versions",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["case_id"],
            ["cases.id"],
            name=op.f("fk_analysis_runs_case_id_cases"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["created_by"], ["users.id"], name=op.f("fk_analysis_runs_created_by_users")
        ),
        sa.ForeignKeyConstraint(
            ["job_id"], ["jobs.id"], name=op.f("fk_analysis_runs_job_id_jobs"), ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_analysis_runs")),
    )
    op.create_index(
        "ix_analysis_runs_case_feature_started",
        "analysis_runs",
        ["case_id", "feature", "started_at"],
        unique=False,
    )
    op.create_table(
        "calculations",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("case_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("value", sa.Numeric(precision=20, scale=6), nullable=False),
        sa.Column("unit", sa.String(length=32), nullable=False),
        sa.Column("formula", sa.Text(), nullable=False),
        sa.Column("inputs", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("working", sa.Text(), nullable=False),
        sa.Column("evidence", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["case_id"],
            ["cases.id"],
            name=op.f("fk_calculations_case_id_cases"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["analysis_runs.id"],
            name=op.f("fk_calculations_run_id_analysis_runs"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_calculations")),
    )
    op.create_index("ix_calculations_run_id", "calculations", ["run_id"], unique=False)
    op.create_table(
        "completeness_results",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("case_id", sa.Uuid(), nullable=False),
        sa.Column("items", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "overall_status",
            sa.Enum(
                "complete",
                "incomplete",
                "needs_review",
                name="overall_status",
                native_enum=False,
                create_constraint=True,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column("updated_by", sa.Uuid(), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["case_id"],
            ["cases.id"],
            name=op.f("fk_completeness_results_case_id_cases"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["analysis_runs.id"],
            name=op.f("fk_completeness_results_run_id_analysis_runs"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["updated_by"], ["users.id"], name=op.f("fk_completeness_results_updated_by_users")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_completeness_results")),
        sa.UniqueConstraint("run_id", name="uq_completeness_results_run_id"),
    )
    op.create_index(
        "ix_completeness_results_case_id", "completeness_results", ["case_id"], unique=False
    )
    op.create_table(
        "income_components",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("borrower", sa.Text(), nullable=False),
        sa.Column("employer", sa.Text(), nullable=True),
        sa.Column(
            "component",
            sa.Enum(
                "base",
                "overtime",
                "bonus",
                "commission",
                name="component",
                native_enum=False,
                create_constraint=True,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column("current_period", sa.Numeric(precision=14, scale=2), nullable=True),
        sa.Column("ytd", sa.Numeric(precision=14, scale=2), nullable=True),
        sa.Column("monthly", sa.Numeric(precision=14, scale=2), nullable=False),
        sa.Column("included", sa.Boolean(), nullable=False),
        sa.Column("exclusion_reason", sa.Text(), nullable=True),
        sa.Column("original_included", sa.Boolean(), nullable=False),
        sa.Column("original_exclusion_reason", sa.Text(), nullable=True),
        sa.Column("review_reason", sa.Text(), nullable=True),
        sa.Column("calculation_id", sa.Uuid(), nullable=True),
        sa.Column("updated_by", sa.Uuid(), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "included OR exclusion_reason IS NOT NULL",
            name=op.f("ck_income_components_excluded_has_reason"),
        ),
        sa.ForeignKeyConstraint(
            ["calculation_id"],
            ["calculations.id"],
            name=op.f("fk_income_components_calculation_id_calculations"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["analysis_runs.id"],
            name=op.f("fk_income_components_run_id_analysis_runs"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["updated_by"], ["users.id"], name=op.f("fk_income_components_updated_by_users")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_income_components")),
    )
    op.create_index("ix_income_components_run_id", "income_components", ["run_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_income_components_run_id", table_name="income_components")
    op.drop_table("income_components")
    op.drop_index("ix_completeness_results_case_id", table_name="completeness_results")
    op.drop_table("completeness_results")
    op.drop_index("ix_calculations_run_id", table_name="calculations")
    op.drop_table("calculations")
    op.drop_index("ix_analysis_runs_case_feature_started", table_name="analysis_runs")
    op.drop_table("analysis_runs")
    op.drop_table("config_versions")

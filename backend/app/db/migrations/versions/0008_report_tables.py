"""reports, findings, conditions, sign-offs, agent runs, waterfall results and lender views

Revision ID: 0008
Revises: 0007
Create Date: 2026-11-23

The shared agent and rules tables docs/database-schema.md lists as due on D6. Arindam owns the shape
of ``reports`` and ``agent_runs`` (his agents write them); this is the migration. The guideline
tables (``guideline_sources``, ``rag_chunks``, ``guideline_questions``) wait for the embedding size
to be confirmed, and come in their own migration.

Columns the doc does not list: ``reports.source`` (the agents' draft, or the seeded sample the demo
starts from), ``conditions.position`` (display order), ``sign_offs.report_version`` (which version
of the report the person reviewed), ``waterfall_results.original_status`` and ``overridden_at``
(what the rules decided, kept beside an override: rule 6) and ``created_at`` everywhere.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

PRIORITIES = ("significant", "attention", "information")
STATUSES = ("met", "not_met", "not_evaluable", "not_reached", "needs_confirmation")


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
        "reports",
        _id(),
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("case_id", sa.Uuid(), nullable=False),
        sa.Column("kind", _enum("kind", "underwriting", "lm_recommendation"), nullable=False),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.Column(
            "sections",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "guardrail_results",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "status",
            _enum("status", "draft", "in_review", "signed_off"),
            server_default="draft",
            nullable=False,
        ),
        sa.Column(
            "source",
            _enum("source", "agents", "seeded_sample"),
            server_default="agents",
            nullable=False,
        ),
        _created_at(),
        sa.CheckConstraint("version >= 1", name=op.f("ck_reports_version_positive")),
        sa.ForeignKeyConstraint(
            ["case_id"], ["cases.id"], name=op.f("fk_reports_case_id_cases"), ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["analysis_runs.id"],
            name=op.f("fk_reports_run_id_analysis_runs"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_reports")),
        sa.UniqueConstraint("run_id", "version", name="uq_reports_run_id_version"),
    )
    op.create_index("ix_reports_case_id", "reports", ["case_id"], unique=False)

    op.create_table(
        "findings",
        _id(),
        sa.Column("report_id", sa.Uuid(), nullable=False),
        sa.Column("priority", _enum("priority", *PRIORITIES), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("detail", sa.Text(), nullable=False),
        sa.Column("evidence", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("flag_id", sa.Uuid(), nullable=True),
        _created_at(),
        sa.ForeignKeyConstraint(
            ["flag_id"], ["flags.id"], name=op.f("fk_findings_flag_id_flags"), ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["report_id"],
            ["reports.id"],
            name=op.f("fk_findings_report_id_reports"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_findings")),
    )
    op.create_index("ix_findings_report_id", "findings", ["report_id"], unique=False)

    op.create_table(
        "conditions",
        _id(),
        sa.Column("report_id", sa.Uuid(), nullable=False),
        sa.Column("position", sa.Integer(), server_default="0", nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("priority", _enum("priority", *PRIORITIES), nullable=False),
        sa.Column("source", _enum("source", "agent", "user"), nullable=False),
        sa.Column(
            "decision",
            _enum("decision", "pending", "accepted", "edited", "rejected"),
            server_default="pending",
            nullable=False,
        ),
        sa.Column("edited_text", sa.Text(), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("decided_by", sa.Uuid(), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        _created_at(),
        sa.CheckConstraint(
            "decision = 'pending' OR (decided_by IS NOT NULL AND decided_at IS NOT NULL)",
            name=op.f("ck_conditions_decision_has_who_and_when"),
        ),
        sa.CheckConstraint(
            "decision <> 'edited' OR edited_text IS NOT NULL",
            name=op.f("ck_conditions_edit_has_text"),
        ),
        sa.CheckConstraint(
            "decision NOT IN ('edited', 'rejected') OR reason IS NOT NULL",
            name=op.f("ck_conditions_edit_or_reject_has_reason"),
        ),
        sa.ForeignKeyConstraint(
            ["decided_by"], ["users.id"], name=op.f("fk_conditions_decided_by_users")
        ),
        sa.ForeignKeyConstraint(
            ["report_id"],
            ["reports.id"],
            name=op.f("fk_conditions_report_id_reports"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_conditions")),
    )
    op.create_index("ix_conditions_report_id", "conditions", ["report_id"], unique=False)

    op.create_table(
        "sign_offs",
        _id(),
        sa.Column("report_id", sa.Uuid(), nullable=False),
        sa.Column("case_id", sa.Uuid(), nullable=False),
        sa.Column("report_version", sa.Integer(), nullable=False),
        sa.Column("signed_by", sa.Uuid(), nullable=False),
        sa.Column("role", sa.String(length=32), nullable=False),
        sa.Column(
            "signed_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column("note", sa.Text(), nullable=True),
        _created_at(),
        sa.CheckConstraint(
            "report_version >= 1", name=op.f("ck_sign_offs_report_version_positive")
        ),
        sa.CheckConstraint(
            "role IN ('underwriter', 'lm_specialist', 'admin')",
            name=op.f("ck_sign_offs_role_is_a_role"),
        ),
        sa.ForeignKeyConstraint(
            ["case_id"], ["cases.id"], name=op.f("fk_sign_offs_case_id_cases"), ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["report_id"],
            ["reports.id"],
            name=op.f("fk_sign_offs_report_id_reports"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["signed_by"], ["users.id"], name=op.f("fk_sign_offs_signed_by_users")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_sign_offs")),
    )
    op.create_index("ix_sign_offs_report_id", "sign_offs", ["report_id"], unique=False)

    op.create_table(
        "agent_runs",
        _id(),
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("agent", _enum("agent", "researcher", "writer", "critic"), nullable=False),
        sa.Column("attempt", sa.Integer(), server_default="1", nullable=False),
        sa.Column(
            "status",
            _enum("status", "queued", "running", "succeeded", "failed"),
            nullable=False,
        ),
        sa.Column("provider", sa.String(length=32), nullable=True),
        sa.Column("model", sa.String(length=100), nullable=True),
        sa.Column("prompt_id", sa.String(length=100), nullable=True),
        sa.Column("output", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        _created_at(),
        sa.CheckConstraint("attempt >= 1", name=op.f("ck_agent_runs_attempt_positive")),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["analysis_runs.id"],
            name=op.f("fk_agent_runs_run_id_analysis_runs"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_agent_runs")),
        sa.UniqueConstraint(
            "run_id", "agent", "attempt", name="uq_agent_runs_run_id_agent_attempt"
        ),
    )

    op.create_table(
        "waterfall_results",
        _id(),
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("rule_set_version", sa.String(length=100), nullable=False),
        sa.Column("order_no", sa.Integer(), nullable=False),
        sa.Column(
            "option",
            _enum(
                "option",
                "repayment_plan",
                "forbearance",
                "payment_deferral",
                "loan_modification",
                "short_sale",
                "deed_in_lieu",
            ),
            nullable=False,
        ),
        sa.Column("status", _enum("status", *STATUSES), nullable=False),
        sa.Column("original_status", _enum("original_status", *STATUSES), nullable=False),
        sa.Column(
            "conditions",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column("overridden", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("override_reason", sa.Text(), nullable=True),
        sa.Column("overridden_by", sa.Uuid(), nullable=True),
        sa.Column("overridden_at", sa.DateTime(timezone=True), nullable=True),
        _created_at(),
        sa.CheckConstraint("order_no >= 1", name=op.f("ck_waterfall_results_order_no_positive")),
        sa.CheckConstraint(
            "NOT overridden OR (override_reason IS NOT NULL AND overridden_by IS NOT NULL)",
            name=op.f("ck_waterfall_results_override_has_reason_and_who"),
        ),
        sa.ForeignKeyConstraint(
            ["overridden_by"], ["users.id"], name=op.f("fk_waterfall_results_overridden_by_users")
        ),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["analysis_runs.id"],
            name=op.f("fk_waterfall_results_run_id_analysis_runs"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_waterfall_results")),
        sa.UniqueConstraint("run_id", "option", name="uq_waterfall_results_run_id_option"),
    )
    op.create_index("ix_waterfall_results_run_id", "waterfall_results", ["run_id"], unique=False)

    op.create_table(
        "lender_views",
        _id(),
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("foreclosure_loss", sa.Numeric(precision=14, scale=2), nullable=False),
        sa.Column("modification_cost", sa.Numeric(precision=14, scale=2), nullable=False),
        sa.Column("advantage", sa.Numeric(precision=14, scale=2), nullable=False),
        sa.Column("settings", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("calculation_ids", postgresql.ARRAY(sa.Uuid()), nullable=False),
        _created_at(),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["analysis_runs.id"],
            name=op.f("fk_lender_views_run_id_analysis_runs"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_lender_views")),
        sa.UniqueConstraint("run_id", name="uq_lender_views_run_id"),
    )


def downgrade() -> None:
    op.drop_table("lender_views")
    op.drop_index("ix_waterfall_results_run_id", table_name="waterfall_results")
    op.drop_table("waterfall_results")
    op.drop_table("agent_runs")
    op.drop_index("ix_sign_offs_report_id", table_name="sign_offs")
    op.drop_table("sign_offs")
    op.drop_index("ix_conditions_report_id", table_name="conditions")
    op.drop_table("conditions")
    op.drop_index("ix_findings_report_id", table_name="findings")
    op.drop_table("findings")
    op.drop_index("ix_reports_case_id", table_name="reports")
    op.drop_table("reports")

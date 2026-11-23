"""hardship profiles

Revision ID: 0006
Revises: 0005
Create Date: 2026-11-23

The ``hardship_profiles`` table from docs/database-schema.md (due D5: the v0.5 demo shows the letter
profile). One profile per ``analysis_runs`` row of feature ``hardship``.

Three columns are not in the doc: ``document_id`` (a line ID is only unique within a document, so
the profile names the letter its quotes are on), ``enclosed_documents`` (part of the profile
hardship@1 returns) and ``source`` (a model's reading, or the seeded sample the demo starts from).
Each profile item is one jsonb value that keeps its quote, its line IDs and whether code verified
the quote.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "hardship_profiles",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("case_id", sa.Uuid(), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=True),
        sa.Column("primary_reason", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "reasons",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column("onset", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("duration", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("intent", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "timeline",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "enclosed_documents",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "source",
            sa.Enum(
                "model",
                "seeded_sample",
                name="source",
                native_enum=False,
                create_constraint=True,
                length=32,
            ),
            server_default="model",
            nullable=False,
        ),
        sa.Column("confirmed_by", sa.Uuid(), nullable=True),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["case_id"],
            ["cases.id"],
            name=op.f("fk_hardship_profiles_case_id_cases"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["confirmed_by"], ["users.id"], name=op.f("fk_hardship_profiles_confirmed_by_users")
        ),
        sa.ForeignKeyConstraint(
            ["document_id"],
            ["documents.id"],
            name=op.f("fk_hardship_profiles_document_id_documents"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["analysis_runs.id"],
            name=op.f("fk_hardship_profiles_run_id_analysis_runs"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_hardship_profiles")),
        sa.UniqueConstraint("run_id", name="uq_hardship_profiles_run_id"),
    )
    op.create_index("ix_hardship_profiles_case_id", "hardship_profiles", ["case_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_hardship_profiles_case_id", table_name="hardship_profiles")
    op.drop_table("hardship_profiles")

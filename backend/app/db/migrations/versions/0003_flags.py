"""flags

Revision ID: 0003
Revises: 0002
Create Date: 2026-11-18

Adds the one table due on D3 (docs/database-schema.md, section 2): ``flags``, with the doc's
columns plus ``created_at`` (the "every row" convention). ``fields.flags`` is already gone
(migration 0002 removed it), so there is nothing to drop here.

``(entity_type, entity_id, code)`` is unique, so a check can never flag the same thing twice.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "flags",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("case_id", sa.Uuid(), nullable=False),
        sa.Column("feature", sa.String(length=64), nullable=False),
        sa.Column("entity_type", sa.String(length=32), nullable=False),
        sa.Column("entity_id", sa.Uuid(), nullable=False),
        sa.Column("code", sa.String(length=32), nullable=False),
        sa.Column(
            "severity",
            sa.Enum(
                "error",
                "warning",
                "info",
                name="severity",
                native_enum=False,
                create_constraint=True,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("evidence", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "status",
            sa.Enum(
                "open",
                "resolved",
                "overridden",
                name="status",
                native_enum=False,
                create_constraint=True,
                length=32,
            ),
            server_default="open",
            nullable=False,
        ),
        sa.Column("resolved_by", sa.Uuid(), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["case_id"], ["cases.id"], name=op.f("fk_flags_case_id_cases"), ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["resolved_by"], ["users.id"], name=op.f("fk_flags_resolved_by_users")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_flags")),
        sa.UniqueConstraint("entity_type", "entity_id", "code", name="uq_flags_entity_code"),
    )
    op.create_index("ix_flags_case_id", "flags", ["case_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_flags_case_id", table_name="flags")
    op.drop_table("flags")

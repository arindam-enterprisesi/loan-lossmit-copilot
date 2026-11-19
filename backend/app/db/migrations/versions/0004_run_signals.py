"""extraction_runs.signals

Revision ID: 0004
Revises: 0003
Create Date: 2026-11-18

One small column. The extractor reports "signs the document is incomplete" (a "continued" notice, a
cut-off table; Feature Design 1.5). The checks re-run, with no model call, whenever a reviewer
corrects a value, so those signals must be kept with the run. ``extraction_runs`` is not in
docs/database-schema.md (it is the 35th table, kept for the contract's run_id, prompt_id, provider
and model), so this column is not a difference from the doc.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "extraction_runs",
        sa.Column(
            "signals",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_column("extraction_runs", "signals")

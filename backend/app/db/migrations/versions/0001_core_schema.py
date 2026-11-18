"""core schema

Revision ID: 0001
Revises:
Create Date: 2026-11-17 22:52:03.820297
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # docker/postgres/init also creates these, but only when the data volume is first created.
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")

    op.create_table(
        "audit_events",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column(
            "at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column("actor", sa.Text(), nullable=False),
        sa.Column("case_id", sa.Uuid(), nullable=True),
        sa.Column("action", sa.Text(), nullable=False),
        sa.Column("entity", sa.Text(), nullable=False),
        sa.Column("before", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("after", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_audit_events")),
    )
    op.create_index("ix_audit_events_case_id_at", "audit_events", ["case_id", "at"], unique=False)
    op.create_table(
        "users",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("username", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column(
            "role",
            sa.Enum(
                "underwriter",
                "lm_specialist",
                "admin",
                name="role",
                native_enum=False,
                create_constraint=True,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column("password_hash", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_users")),
        sa.UniqueConstraint("username", name=op.f("uq_users_username")),
    )
    op.create_table(
        "cases",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column(
            "pillar",
            sa.Enum(
                "underwriting",
                "loss_mitigation",
                name="pillar",
                native_enum=False,
                create_constraint=True,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("borrower_names", postgresql.ARRAY(sa.Text()), nullable=True),
        sa.Column(
            "employment_type",
            sa.Enum(
                "wage_earner",
                "self_employed",
                "retired",
                "other",
                name="employment_type",
                native_enum=False,
                create_constraint=True,
                length=32,
            ),
            nullable=True,
        ),
        sa.Column("reference_date", sa.Date(), nullable=True),
        sa.Column("status", sa.String(length=32), server_default="open", nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["created_by"], ["users.id"], name=op.f("fk_cases_created_by_users")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_cases")),
    )
    op.create_table(
        "documents",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("case_id", sa.Uuid(), nullable=False),
        sa.Column("file_name", sa.Text(), nullable=False),
        sa.Column("file_key", sa.Text(), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("mime", sa.String(length=100), nullable=False),
        sa.Column("page_count", sa.Integer(), nullable=True),
        sa.Column("declared_type", sa.String(length=64), nullable=True),
        sa.Column("doc_type", sa.String(length=64), nullable=True),
        sa.Column(
            "doc_type_certainty",
            sa.Enum(
                "high",
                "medium",
                "low",
                name="doc_type_certainty",
                native_enum=False,
                create_constraint=True,
                length=32,
            ),
            nullable=True,
        ),
        sa.Column(
            "status",
            sa.Enum(
                "uploaded",
                "processing",
                "type_needed",
                "needs_review",
                "reviewed",
                "failed",
                name="status",
                native_enum=False,
                create_constraint=True,
                length=32,
            ),
            server_default="uploaded",
            nullable=False,
        ),
        sa.Column("owner", sa.Text(), nullable=True),
        sa.Column("period_start", sa.Date(), nullable=True),
        sa.Column("period_end", sa.Date(), nullable=True),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("sha256 ~ '^[0-9a-f]{64}$'", name=op.f("ck_documents_sha256_hex")),
        sa.ForeignKeyConstraint(
            ["case_id"], ["cases.id"], name=op.f("fk_documents_case_id_cases"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_documents")),
    )
    op.create_index("ix_documents_case_id_sha256", "documents", ["case_id", "sha256"], unique=False)
    op.create_table(
        "jobs",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("kind", sa.String(length=64), nullable=False),
        sa.Column("case_id", sa.Uuid(), nullable=True),
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
        sa.Column("progress", sa.Float(), server_default="0", nullable=False),
        sa.Column("stage", sa.String(length=64), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("progress >= 0 AND progress <= 1", name=op.f("ck_jobs_progress_range")),
        sa.ForeignKeyConstraint(
            ["case_id"], ["cases.id"], name=op.f("fk_jobs_case_id_cases"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_jobs")),
    )
    op.create_index("ix_jobs_case_id", "jobs", ["case_id"], unique=False)
    op.create_table(
        "extraction_runs",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("doc_type", sa.String(length=64), nullable=False),
        sa.Column("active", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("prompt_id", sa.String(length=100), nullable=True),
        sa.Column("provider", sa.String(length=50), nullable=True),
        sa.Column("model", sa.String(length=100), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["document_id"],
            ["documents.id"],
            name=op.f("fk_extraction_runs_document_id_documents"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_extraction_runs")),
        sa.UniqueConstraint("id", "document_id", name="uq_extraction_runs_id_document_id"),
    )
    op.create_index(
        "uq_extraction_runs_one_active",
        "extraction_runs",
        ["document_id"],
        unique=True,
        postgresql_where=sa.text("active"),
    )
    op.create_table(
        "pages",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("number", sa.Integer(), nullable=False),
        sa.Column("image_key", sa.Text(), nullable=False),
        sa.Column("width", sa.Integer(), nullable=False),
        sa.Column("height", sa.Integer(), nullable=False),
        sa.CheckConstraint("number >= 1", name=op.f("ck_pages_number_positive")),
        sa.CheckConstraint("width > 0 AND height > 0", name=op.f("ck_pages_size_positive")),
        sa.ForeignKeyConstraint(
            ["document_id"],
            ["documents.id"],
            name=op.f("fk_pages_document_id_documents"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_pages")),
        sa.UniqueConstraint("document_id", "number", name="uq_pages_document_id_number"),
    )
    op.create_table(
        "fields",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("value", sa.Text(), nullable=True),
        sa.Column("original_value", sa.Text(), nullable=True),
        sa.Column(
            "certainty",
            sa.Enum(
                "high",
                "medium",
                "low",
                name="certainty",
                native_enum=False,
                create_constraint=True,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column(
            "line_ids", postgresql.ARRAY(sa.Text()), server_default=sa.text("'{}'"), nullable=False
        ),
        sa.Column(
            "flags",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "review_status",
            sa.Enum(
                "unreviewed",
                "confirmed",
                "corrected",
                "rejected",
                name="review_status",
                native_enum=False,
                create_constraint=True,
                length=32,
            ),
            server_default="unreviewed",
            nullable=False,
        ),
        sa.Column("reviewed_by", sa.Uuid(), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("review_reason", sa.Text(), nullable=True),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.CheckConstraint("name ~ '^[a-z][a-z0-9_]*$'", name=op.f("ck_fields_name_format")),
        sa.ForeignKeyConstraint(
            ["reviewed_by"], ["users.id"], name=op.f("fk_fields_reviewed_by_users")
        ),
        sa.ForeignKeyConstraint(
            ["run_id", "document_id"],
            ["extraction_runs.id", "extraction_runs.document_id"],
            name=op.f("fk_fields_run_id_extraction_runs"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_fields")),
        sa.UniqueConstraint("run_id", "name", name="uq_fields_run_id_name"),
    )
    op.create_index("ix_fields_document_id", "fields", ["document_id"], unique=False)
    op.create_table(
        "lines",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("page_id", sa.Uuid(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("bbox", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.CheckConstraint("id ~ '^p[0-9]+-L[0-9]+$'", name=op.f("ck_lines_id_format")),
        sa.CheckConstraint(
            "confidence IS NULL OR (confidence >= 0 AND confidence <= 1)",
            name=op.f("ck_lines_confidence_range"),
        ),
        sa.ForeignKeyConstraint(
            ["document_id"],
            ["documents.id"],
            name=op.f("fk_lines_document_id_documents"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["page_id"], ["pages.id"], name=op.f("fk_lines_page_id_pages"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", "document_id", name=op.f("pk_lines")),
    )
    op.create_index("ix_lines_page_id", "lines", ["page_id"], unique=False)

    # audit_events is append-only. The app connects as the table owner, so revoking
    # grants would not stop it; a trigger does. One statement per execute: asyncpg
    # cannot run several commands in one prepared statement.
    op.execute(
        """
        CREATE FUNCTION audit_events_block_mutation() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION 'audit_events is append-only: % is not allowed', TG_OP;
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER audit_events_no_update_delete
        BEFORE UPDATE OR DELETE ON audit_events
        FOR EACH ROW EXECUTE FUNCTION audit_events_block_mutation()
        """
    )
    op.execute(
        """
        CREATE TRIGGER audit_events_no_truncate
        BEFORE TRUNCATE ON audit_events
        FOR EACH STATEMENT EXECUTE FUNCTION audit_events_block_mutation()
        """
    )


def downgrade() -> None:
    # Dropping the table drops its triggers; the function is separate. DROP is not blocked.
    op.drop_table("audit_events")
    op.execute("DROP FUNCTION audit_events_block_mutation()")

    op.drop_index("ix_lines_page_id", table_name="lines")
    op.drop_table("lines")
    op.drop_index("ix_fields_document_id", table_name="fields")
    op.drop_table("fields")
    op.drop_table("pages")
    op.drop_index(
        "uq_extraction_runs_one_active",
        table_name="extraction_runs",
        postgresql_where=sa.text("active"),
    )
    op.drop_table("extraction_runs")
    op.drop_index("ix_jobs_case_id", table_name="jobs")
    op.drop_table("jobs")
    op.drop_index("ix_documents_case_id_sha256", table_name="documents")
    op.drop_table("documents")
    op.drop_table("cases")
    op.drop_table("users")

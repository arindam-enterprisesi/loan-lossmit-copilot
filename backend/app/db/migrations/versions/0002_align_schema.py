"""align the D1 tables with docs/database-schema.md

Revision ID: 0002
Revises: 0001
Create Date: 2026-11-18

Renames and adds columns on the eight D1 tables so they match the schema doc (names, types and
conventions). Where the doc and contracts/openapi.yaml differ on a value (roles, pillars, review
statuses) the contract's value is kept. extraction_runs is not in the doc and is untouched.

Existing rows are carried over:
- cases.case_ref is backfilled per pillar (LP-0001, LP-0002 ... by created_at) and the two
  sequences that hand out new refs are moved past the highest one;
- cases.borrower_names changes from text[] to a jsonb array;
- lines get a uuid id; the old text id becomes line_ref;
- audit_events.actor / entity are split into actor_id + role and entity_type + entity_id. The
  append-only trigger blocks UPDATE, so it is switched off for that one statement, inside this
  transaction, and switched back on straight after.

The migration refuses to run, instead of silently losing information, if any fields.flags is
non-empty (flags get their own table on D3) or any audit_events.entity is not 'type' or
'type:<uuid>'.
"""

from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

UUID_PATTERN = "[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
CASE_REF_SEQUENCES = (("LP", "case_ref_lp_seq"), ("LM", "case_ref_lm_seq"))
AUDIT_GUARD = "audit_events_no_update_delete"  # the append-only trigger from 0001


def _created_at() -> sa.Column[Any]:
    return sa.Column(
        "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
    )


def upgrade() -> None:
    # --- users -----------------------------------------------------------------------------
    op.add_column("users", sa.Column("email", sa.String(length=254), nullable=True))

    # --- cases -----------------------------------------------------------------------------
    op.add_column("cases", sa.Column("tenant_id", sa.Uuid(), nullable=True))
    op.add_column("cases", sa.Column("case_ref", sa.String(length=32), nullable=True))
    for _, sequence in CASE_REF_SEQUENCES:
        op.execute(f"CREATE SEQUENCE {sequence}")
    op.execute(
        """
        UPDATE cases SET case_ref = ranked.prefix || '-' || lpad(ranked.n::text, 4, '0')
        FROM (
            SELECT id,
                   CASE pillar WHEN 'underwriting' THEN 'LP' ELSE 'LM' END AS prefix,
                   row_number() OVER (PARTITION BY pillar ORDER BY created_at, id) AS n
            FROM cases
        ) AS ranked
        WHERE cases.id = ranked.id
        """
    )
    for prefix, sequence in CASE_REF_SEQUENCES:
        # NULL (no such cases) leaves the sequence alone.
        op.execute(
            f"SELECT setval('{sequence}', max(CAST(substr(case_ref, 4) AS integer))) "
            f"FROM cases WHERE case_ref LIKE '{prefix}-%'"
        )
    op.alter_column("cases", "case_ref", nullable=False)
    op.create_unique_constraint(op.f("uq_cases_case_ref"), "cases", ["case_ref"])
    op.create_check_constraint(
        op.f("ck_cases_case_ref_format"), "cases", "case_ref ~ '^(LP|LM)-[0-9]{4,}$'"
    )
    op.alter_column(
        "cases",
        "borrower_names",
        type_=postgresql.JSONB(astext_type=sa.Text()),
        postgresql_using="to_jsonb(borrower_names)",
    )
    op.create_check_constraint(
        op.f("ck_cases_borrower_names_is_array"),
        "cases",
        "borrower_names IS NULL OR jsonb_typeof(borrower_names) = 'array'",
    )

    # --- documents -------------------------------------------------------------------------
    op.alter_column("documents", "file_key", new_column_name="s3_key")
    op.alter_column("documents", "owner", new_column_name="borrower")
    op.add_column("documents", sa.Column("size_bytes", sa.BigInteger(), nullable=True))
    # No upload endpoint exists yet, so no real document row can be here; 0 only fills a stray one.
    op.execute("UPDATE documents SET size_bytes = 0")
    op.alter_column("documents", "size_bytes", nullable=False)
    op.create_check_constraint(
        op.f("ck_documents_size_bytes_non_negative"), "documents", "size_bytes >= 0"
    )
    op.add_column("documents", sa.Column("doc_type_source", sa.String(length=32), nullable=True))
    op.create_check_constraint(
        op.f("ck_documents_doc_type_source"), "documents", "doc_type_source IN ('ai', 'user')"
    )

    # --- pages -----------------------------------------------------------------------------
    op.alter_column("pages", "number", new_column_name="page_no")
    op.alter_column("pages", "image_key", new_column_name="image_s3_key")
    op.execute(
        "ALTER TABLE pages RENAME CONSTRAINT ck_pages_number_positive TO ck_pages_page_no_positive"
    )
    op.execute(
        "ALTER TABLE pages RENAME CONSTRAINT uq_pages_document_id_number "
        "TO uq_pages_document_id_page_no"
    )
    op.add_column("pages", sa.Column("read_by", sa.String(length=32), nullable=True))
    op.create_check_constraint(
        op.f("ck_pages_read_by"), "pages", "read_by IN ('text_layer', 'tesseract')"
    )
    op.add_column("pages", sa.Column("printed_page_label", sa.Text(), nullable=True))
    op.add_column("pages", _created_at())

    # --- lines: the text id (p1-L31) becomes line_ref; a uuid becomes the key ---------------
    op.alter_column("lines", "id", new_column_name="line_ref")
    op.execute("ALTER TABLE lines RENAME CONSTRAINT ck_lines_id_format TO ck_lines_line_ref_format")
    op.drop_constraint(op.f("pk_lines"), "lines", type_="primary")
    # A volatile default, so every existing row gets its own uuid.
    op.add_column(
        "lines",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
    )
    op.create_primary_key(op.f("pk_lines"), "lines", ["id"])
    op.create_unique_constraint(
        "uq_lines_document_id_line_ref", "lines", ["document_id", "line_ref"]
    )
    op.add_column("lines", _created_at())

    # --- fields ----------------------------------------------------------------------------
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM fields WHERE flags <> '[]'::jsonb) THEN
                RAISE EXCEPTION 'fields.flags is not empty; flags move to their own table on D3, '
                    'so this migration will not drop them';
            END IF;
        END
        $$
        """
    )
    op.alter_column("fields", "line_ids", new_column_name="line_refs")
    op.add_column("fields", sa.Column("normalized_value", sa.Text(), nullable=True))
    op.drop_column("fields", "flags")
    op.add_column("fields", _created_at())

    # --- jobs ------------------------------------------------------------------------------
    op.add_column("jobs", sa.Column("document_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        op.f("fk_jobs_document_id_documents"),
        "jobs",
        "documents",
        ["document_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_index("ix_jobs_document_id", "jobs", ["document_id"], unique=False)
    op.add_column("jobs", sa.Column("attempts", sa.Integer(), server_default="0", nullable=False))
    op.create_check_constraint(op.f("ck_jobs_attempts_non_negative"), "jobs", "attempts >= 0")

    # --- audit_events ----------------------------------------------------------------------
    op.execute(
        f"""
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM audit_events
                WHERE entity !~* '^[^:]+(:{UUID_PATTERN})?$'
            ) THEN
                RAISE EXCEPTION 'audit_events.entity is not type or type:uuid, '
                    'so this migration will not drop part of an audit record';
            END IF;
        END
        $$
        """
    )
    op.add_column("audit_events", sa.Column("actor_id", sa.Uuid(), nullable=True))
    op.add_column("audit_events", sa.Column("role", sa.Text(), nullable=True))
    op.add_column("audit_events", sa.Column("entity_type", sa.Text(), nullable=True))
    op.add_column("audit_events", sa.Column("entity_id", sa.Uuid(), nullable=True))
    op.execute(f"ALTER TABLE audit_events DISABLE TRIGGER {AUDIT_GUARD}")
    op.execute(
        f"""
        UPDATE audit_events SET
            actor_id = CASE WHEN actor ~* '^{UUID_PATTERN}$' THEN actor::uuid END,
            role = CASE
                WHEN actor ~* '^{UUID_PATTERN}$'
                    THEN COALESCE((SELECT u.role FROM users u WHERE u.id = actor::uuid), 'unknown')
                ELSE actor
            END,
            entity_type = split_part(entity, ':', 1),
            entity_id = CASE WHEN entity LIKE '%:%' THEN split_part(entity, ':', 2)::uuid END
        """
    )
    op.execute(f"ALTER TABLE audit_events ENABLE TRIGGER {AUDIT_GUARD}")
    op.alter_column("audit_events", "role", nullable=False)
    op.alter_column("audit_events", "entity_type", nullable=False)
    op.drop_column("audit_events", "actor")
    op.drop_column("audit_events", "entity")


def downgrade() -> None:
    # --- audit_events ----------------------------------------------------------------------
    op.add_column("audit_events", sa.Column("actor", sa.Text(), nullable=True))
    op.add_column("audit_events", sa.Column("entity", sa.Text(), nullable=True))
    op.execute(f"ALTER TABLE audit_events DISABLE TRIGGER {AUDIT_GUARD}")
    op.execute(
        """
        UPDATE audit_events SET
            actor = COALESCE(actor_id::text, role),
            entity = CASE
                WHEN entity_id IS NULL THEN entity_type
                ELSE entity_type || ':' || entity_id::text
            END
        """
    )
    op.execute(f"ALTER TABLE audit_events ENABLE TRIGGER {AUDIT_GUARD}")
    op.alter_column("audit_events", "actor", nullable=False)
    op.alter_column("audit_events", "entity", nullable=False)
    for column in ("entity_id", "entity_type", "role", "actor_id"):
        op.drop_column("audit_events", column)

    # --- jobs ------------------------------------------------------------------------------
    op.drop_constraint(op.f("ck_jobs_attempts_non_negative"), "jobs", type_="check")
    op.drop_column("jobs", "attempts")
    op.drop_index("ix_jobs_document_id", table_name="jobs")
    op.drop_constraint(op.f("fk_jobs_document_id_documents"), "jobs", type_="foreignkey")
    op.drop_column("jobs", "document_id")

    # --- fields ----------------------------------------------------------------------------
    op.drop_column("fields", "created_at")
    op.add_column(
        "fields",
        sa.Column(
            "flags",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
    )
    op.drop_column("fields", "normalized_value")
    op.alter_column("fields", "line_refs", new_column_name="line_ids")

    # --- lines -----------------------------------------------------------------------------
    op.drop_column("lines", "created_at")
    op.drop_constraint("uq_lines_document_id_line_ref", "lines", type_="unique")
    op.drop_constraint(op.f("pk_lines"), "lines", type_="primary")
    op.drop_column("lines", "id")
    op.alter_column("lines", "line_ref", new_column_name="id")
    op.create_primary_key(op.f("pk_lines"), "lines", ["id", "document_id"])
    op.execute("ALTER TABLE lines RENAME CONSTRAINT ck_lines_line_ref_format TO ck_lines_id_format")

    # --- pages -----------------------------------------------------------------------------
    op.drop_column("pages", "created_at")
    op.drop_column("pages", "printed_page_label")
    op.drop_constraint(op.f("ck_pages_read_by"), "pages", type_="check")
    op.drop_column("pages", "read_by")
    op.execute(
        "ALTER TABLE pages RENAME CONSTRAINT uq_pages_document_id_page_no "
        "TO uq_pages_document_id_number"
    )
    op.execute(
        "ALTER TABLE pages RENAME CONSTRAINT ck_pages_page_no_positive TO ck_pages_number_positive"
    )
    op.alter_column("pages", "image_s3_key", new_column_name="image_key")
    op.alter_column("pages", "page_no", new_column_name="number")

    # --- documents -------------------------------------------------------------------------
    op.drop_constraint(op.f("ck_documents_doc_type_source"), "documents", type_="check")
    op.drop_column("documents", "doc_type_source")
    op.drop_constraint(op.f("ck_documents_size_bytes_non_negative"), "documents", type_="check")
    op.drop_column("documents", "size_bytes")
    op.alter_column("documents", "borrower", new_column_name="owner")
    op.alter_column("documents", "s3_key", new_column_name="file_key")

    # --- cases -----------------------------------------------------------------------------
    op.drop_constraint(op.f("ck_cases_borrower_names_is_array"), "cases", type_="check")
    # ALTER COLUMN ... TYPE cannot use a subquery, so go through a temporary column.
    op.add_column(
        "cases", sa.Column("borrower_names_text", postgresql.ARRAY(sa.Text()), nullable=True)
    )
    op.execute(
        "UPDATE cases SET borrower_names_text = "
        "ARRAY(SELECT jsonb_array_elements_text(borrower_names)) "
        "WHERE borrower_names IS NOT NULL"
    )
    op.drop_column("cases", "borrower_names")
    op.alter_column("cases", "borrower_names_text", new_column_name="borrower_names")
    op.drop_constraint(op.f("ck_cases_case_ref_format"), "cases", type_="check")
    op.drop_constraint(op.f("uq_cases_case_ref"), "cases", type_="unique")
    op.drop_column("cases", "case_ref")
    op.drop_column("cases", "tenant_id")
    for _, sequence in reversed(CASE_REF_SEQUENCES):
        op.execute(f"DROP SEQUENCE {sequence}")

    # --- users -----------------------------------------------------------------------------
    op.drop_column("users", "email")

"""Integrity rules the schema enforces itself."""

from __future__ import annotations

import uuid

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncConnection

from tests.db.conftest import expect_db_error, insert_case, insert_document


async def _scalar(conn: AsyncConnection, sql: str, **params: object) -> object:
    return (await conn.execute(sa.text(sql), params)).scalar_one()


async def _page(conn: AsyncConnection, document_id: uuid.UUID, page_no: int = 1) -> uuid.UUID:
    result = await conn.execute(
        sa.text(
            "INSERT INTO pages (document_id, page_no, image_s3_key, width, height) "
            "VALUES (:d, :n, 'p.png', 1000, 1400) RETURNING id"
        ),
        {"d": document_id, "n": page_no},
    )
    return result.scalar_one()


async def _line(
    conn: AsyncConnection, document_id: uuid.UUID, page_id: uuid.UUID, line_ref: str
) -> None:
    await conn.execute(
        sa.text(
            "INSERT INTO lines (document_id, page_id, line_ref, text, bbox, confidence) "
            "VALUES (:d, :p, :r, 'Net pay 2,033.61', "
            '\'{"x0": 0.1, "y0": 0.2, "x1": 0.5, "y1": 0.25}\', 0.98)'
        ),
        {"r": line_ref, "d": document_id, "p": page_id},
    )


async def _run(conn: AsyncConnection, document_id: uuid.UUID, *, active: bool = False) -> uuid.UUID:
    result = await conn.execute(
        sa.text(
            "INSERT INTO extraction_runs (document_id, doc_type, active) "
            "VALUES (:d, 'pay_stub', :a) RETURNING id"
        ),
        {"d": document_id, "a": active},
    )
    return result.scalar_one()


async def _field(
    conn: AsyncConnection, run_id: uuid.UUID, document_id: uuid.UUID, name: str = "net_pay"
) -> None:
    await conn.execute(
        sa.text(
            "INSERT INTO fields (document_id, run_id, name, value, original_value, certainty) "
            "VALUES (:d, :r, :n, '2033.61', '2033.61', 'high')"
        ),
        {"d": document_id, "r": run_id, "n": name},
    )


# --- closed value sets (the contract's values; the schema doc's differ, see the PR) --------


async def test_unknown_role_rejected(conn: AsyncConnection) -> None:
    for bad in (
        "boss",
        "processor",
        "compliance",
    ):  # the doc lists the last two; the contract does not
        await expect_db_error(
            conn,
            "INSERT INTO users (username, name, role, password_hash) VALUES (:u, 'X', :r, 'h')",
            u=f"x-{bad}",
            r=bad,
        )


async def test_unknown_pillar_rejected(conn: AsyncConnection, user_id: uuid.UUID) -> None:
    # The schema doc says `loan_processing`; the contract says `underwriting` and wins.
    await expect_db_error(
        conn,
        "INSERT INTO cases (case_ref, pillar, title, created_by) "
        "VALUES ('LP-9001', 'loan_processing', 'T', :u)",
        u=user_id,
    )


async def test_unknown_review_status_rejected(
    conn: AsyncConnection, document_id: uuid.UUID
) -> None:
    run = await _run(conn, document_id)
    # The schema doc says `pending`; the contract says `unreviewed`, and the contract wins.
    await expect_db_error(
        conn,
        "INSERT INTO fields (document_id, run_id, name, certainty, review_status) "
        "VALUES (:d, :r, 'x', 'low', 'pending')",
        d=document_id,
        r=run,
    )


# --- users -------------------------------------------------------------------------------


async def test_user_email_is_optional(conn: AsyncConnection, user_id: uuid.UUID) -> None:
    assert await _scalar(conn, "SELECT email FROM users WHERE id = :u", u=user_id) is None
    await conn.execute(
        sa.text("UPDATE users SET email = 'daniel@example.test' WHERE id = :u"), {"u": user_id}
    )


# --- cases -------------------------------------------------------------------------------


async def test_case_profile_starts_empty(conn: AsyncConnection, case_id: uuid.UUID) -> None:
    row = (
        await conn.execute(
            sa.text(
                "SELECT borrower_names, employment_type, reference_date, status, tenant_id "
                "FROM cases WHERE id = :c"
            ),
            {"c": case_id},
        )
    ).one()
    assert tuple(row) == (None, None, None, "open", None)


async def test_tenant_id_is_a_plain_uuid_with_no_foreign_key(
    conn: AsyncConnection, case_id: uuid.UUID
) -> None:
    # Row-Level Security arrives in phase 2; until then any uuid (or none) is accepted.
    await conn.execute(
        sa.text("UPDATE cases SET tenant_id = :t WHERE id = :c"), {"t": uuid.uuid4(), "c": case_id}
    )


async def test_case_ref_is_required_unique_and_formatted(
    conn: AsyncConnection, user_id: uuid.UUID
) -> None:
    await insert_case(conn, user_id, case_ref="LP-0042")
    await insert_case(conn, user_id, pillar="loss_mitigation", case_ref="LM-0042")
    insert = (
        "INSERT INTO cases (case_ref, pillar, title, created_by) "
        "VALUES (:r, 'underwriting', 'T', :u)"
    )
    await expect_db_error(conn, insert, r="LP-0042", u=user_id)  # taken
    for bad in ("LP-1", "XX-0001", "lp-0001", "LP0001", "LP-0001 ", "LP-00a1", ""):
        await expect_db_error(conn, insert, r=bad, u=user_id)
    await expect_db_error(
        conn,
        "INSERT INTO cases (pillar, title, created_by) VALUES ('underwriting', 'T', :u)",
        u=user_id,
    )
    # Five digits is still a valid ref once the counter passes 9999.
    await insert_case(conn, user_id, case_ref="LP-10000")


async def test_borrower_names_must_be_a_json_array(
    conn: AsyncConnection, case_id: uuid.UUID
) -> None:
    update = "UPDATE cases SET borrower_names = CAST(:n AS jsonb) WHERE id = :c"
    for bad in ('"Daniel Reyes"', '{"name": "Daniel"}', "42"):
        await expect_db_error(conn, update, n=bad, c=case_id)
    await conn.execute(sa.text(update), {"n": '["Daniel Reyes", "Maria Reyes"]', "c": case_id})
    stored = await _scalar(conn, "SELECT borrower_names FROM cases WHERE id = :c", c=case_id)
    assert stored == ["Daniel Reyes", "Maria Reyes"]


# --- documents ---------------------------------------------------------------------------


async def test_doc_type_is_free_text(conn: AsyncConnection, document_id: uuid.UUID) -> None:
    # Document types are administrator-managed configuration, so there is no CHECK.
    await conn.execute(
        sa.text("UPDATE documents SET doc_type = 'a_type_added_later' WHERE id = :d"),
        {"d": document_id},
    )


async def test_doc_type_source_is_ai_or_user(conn: AsyncConnection, document_id: uuid.UUID) -> None:
    update = "UPDATE documents SET doc_type_source = :s WHERE id = :d"
    for good in ("ai", "user", None):
        await conn.execute(sa.text(update), {"s": good, "d": document_id})
    await expect_db_error(conn, update, s="robot", d=document_id)


async def test_sha256_must_be_64_hex(conn: AsyncConnection, case_id: uuid.UUID) -> None:
    for bad in ("abc", "Z" * 64, "A" * 64):
        await expect_db_error(
            conn,
            "INSERT INTO documents (case_id, file_name, s3_key, sha256, mime, size_bytes) "
            "VALUES (:c, 'a.pdf', 'k', :h, 'application/pdf', 1)",
            c=case_id,
            h=bad,
        )


async def test_size_bytes_is_required_and_not_negative(
    conn: AsyncConnection, case_id: uuid.UUID
) -> None:
    await expect_db_error(
        conn,
        "INSERT INTO documents (case_id, file_name, s3_key, sha256, mime, size_bytes) "
        "VALUES (:c, 'a.pdf', 'k', :h, 'application/pdf', -1)",
        c=case_id,
        h="a" * 64,
    )
    await expect_db_error(
        conn,
        "INSERT INTO documents (case_id, file_name, s3_key, sha256, mime) "
        "VALUES (:c, 'a.pdf', 'k', :h, 'application/pdf')",
        c=case_id,
        h="a" * 64,
    )


async def test_same_file_twice_in_a_case_is_allowed(
    conn: AsyncConnection, case_id: uuid.UUID
) -> None:
    # The FSD warns about duplicates ("Keep it anyway?", DI-W206); it never blocks them, so
    # (case_id, sha256) is indexed but not unique. (The schema doc's brief asked for unique; the
    # FSD wins.)
    digest = "a" * 64
    await insert_document(conn, case_id, digest)
    await insert_document(conn, case_id, digest)
    count = await _scalar(
        conn,
        "SELECT count(*) FROM documents WHERE case_id = :c AND sha256 = :h",
        c=case_id,
        h=digest,
    )
    assert count == 2


# --- pages -------------------------------------------------------------------------------


async def test_page_numbers_unique_per_document_and_start_at_one(
    conn: AsyncConnection, document_id: uuid.UUID
) -> None:
    await _page(conn, document_id, 1)
    await _page(conn, document_id, 2)
    insert = (
        "INSERT INTO pages (document_id, page_no, image_s3_key, width, height) "
        "VALUES (:d, :n, 'again.png', 10, 10)"
    )
    await expect_db_error(conn, insert, d=document_id, n=1)
    await expect_db_error(conn, insert, d=document_id, n=0)


async def test_page_read_by_and_printed_label(
    conn: AsyncConnection, document_id: uuid.UUID
) -> None:
    page = await _page(conn, document_id)
    row = (
        await conn.execute(
            sa.text("SELECT read_by, printed_page_label, created_at FROM pages WHERE id = :p"),
            {"p": page},
        )
    ).one()
    assert (row.read_by, row.printed_page_label) == (None, None)
    assert row.created_at is not None
    update = "UPDATE pages SET read_by = :r, printed_page_label = 'Page 1 of 3' WHERE id = :p"
    for good in ("text_layer", "tesseract"):
        await conn.execute(sa.text(update), {"r": good, "p": page})
    await expect_db_error(conn, update, r="vision", p=page)


# --- lines -------------------------------------------------------------------------------


async def test_line_ref_format(conn: AsyncConnection, document_id: uuid.UUID) -> None:
    page = await _page(conn, document_id)
    await _line(conn, document_id, page, "p1-L31")
    for bad in ("L31", "p1-31", "p1-L", "P1-L31", "p1-L31 "):
        await expect_db_error(
            conn,
            "INSERT INTO lines (document_id, page_id, line_ref, text, bbox) "
            "VALUES (:d, :p, :r, 't', '{}')",
            r=bad,
            d=document_id,
            p=page,
        )


async def test_lines_have_their_own_uuid_id(conn: AsyncConnection, document_id: uuid.UUID) -> None:
    page = await _page(conn, document_id)
    await _line(conn, document_id, page, "p1-L1")
    await _line(conn, document_id, page, "p1-L2")
    ids = (
        await conn.execute(
            sa.text("SELECT id FROM lines WHERE document_id = :d"), {"d": document_id}
        )
    ).all()
    assert len({row.id for row in ids}) == 2
    assert all(isinstance(row.id, uuid.UUID) for row in ids)


async def test_same_line_ref_allowed_in_two_documents_but_not_twice_in_one(
    conn: AsyncConnection, case_id: uuid.UUID
) -> None:
    first, second = await insert_document(conn, case_id), await insert_document(conn, case_id)
    await _line(conn, first, await _page(conn, first), "p1-L1")
    await _line(conn, second, await _page(conn, second), "p1-L1")
    await expect_db_error(
        conn,
        "INSERT INTO lines (document_id, page_id, line_ref, text, bbox) "
        "SELECT document_id, page_id, 'p1-L1', 'dup', '{}' FROM lines WHERE document_id = :d",
        d=first,
    )


async def test_line_confidence_must_be_a_fraction(
    conn: AsyncConnection, document_id: uuid.UUID
) -> None:
    page = await _page(conn, document_id)
    await expect_db_error(
        conn,
        "INSERT INTO lines (document_id, page_id, line_ref, text, bbox, confidence) "
        "VALUES (:d, :p, 'p1-L2', 't', '{}', 1.5)",
        d=document_id,
        p=page,
    )


# --- extraction runs and fields ----------------------------------------------------------


async def test_field_names_unique_per_run_but_not_across_runs(
    conn: AsyncConnection, document_id: uuid.UUID
) -> None:
    first, second = await _run(conn, document_id), await _run(conn, document_id)
    await _field(conn, first, document_id)
    await _field(conn, second, document_id)  # a re-run produces the same field again
    await expect_db_error(
        conn,
        "INSERT INTO fields (document_id, run_id, name, certainty) "
        "VALUES (:d, :r, 'net_pay', 'low')",
        d=document_id,
        r=first,
    )


async def test_field_name_format(conn: AsyncConnection, document_id: uuid.UUID) -> None:
    run = await _run(conn, document_id)
    for bad in ("Net Pay", "1st", "net-pay"):
        await expect_db_error(
            conn,
            "INSERT INTO fields (document_id, run_id, name, certainty) VALUES (:d, :r, :n, 'low')",
            d=document_id,
            r=run,
            n=bad,
        )


async def test_only_one_active_run_per_document(
    conn: AsyncConnection, document_id: uuid.UUID
) -> None:
    await _run(conn, document_id, active=True)
    await _run(conn, document_id, active=False)
    await _run(conn, document_id, active=False)
    await expect_db_error(
        conn,
        "INSERT INTO extraction_runs (document_id, doc_type, active) VALUES (:d, 'pay_stub', true)",
        d=document_id,
    )


async def test_field_must_belong_to_its_runs_document(
    conn: AsyncConnection, case_id: uuid.UUID
) -> None:
    first, second = await insert_document(conn, case_id), await insert_document(conn, case_id)
    run = await _run(conn, first)
    await expect_db_error(
        conn,
        "INSERT INTO fields (document_id, run_id, name, certainty) VALUES (:d, :r, 'x', 'low')",
        d=second,
        r=run,
    )


async def test_field_defaults(conn: AsyncConnection, document_id: uuid.UUID) -> None:
    run = await _run(conn, document_id)
    await _field(conn, run, document_id)
    row = (
        await conn.execute(
            sa.text(
                "SELECT review_status, version, line_refs, normalized_value, created_at "
                "FROM fields WHERE run_id = :r"
            ),
            {"r": run},
        )
    ).one()
    assert tuple(row)[:4] == ("unreviewed", 1, [], None)
    assert row.created_at is not None


async def test_fields_have_no_flags_column(conn: AsyncConnection) -> None:
    # Flags move to their own table on D3.
    columns = await conn.execute(
        sa.text(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_schema = 'public' AND table_name = 'fields'"
        )
    )
    names = {row[0] for row in columns}
    assert "flags" not in names and "line_ids" not in names
    assert {"line_refs", "normalized_value", "original_value", "version", "reviewed_at"} <= names


# --- jobs --------------------------------------------------------------------------------


async def test_job_progress_range_and_defaults(conn: AsyncConnection, case_id: uuid.UUID) -> None:
    row = (
        await conn.execute(
            sa.text(
                "INSERT INTO jobs (kind, case_id) VALUES ('document_processing', :c) "
                "RETURNING status, progress, attempts, document_id"
            ),
            {"c": case_id},
        )
    ).one()
    assert tuple(row) == ("queued", 0.0, 0, None)
    await expect_db_error(
        conn, "INSERT INTO jobs (kind, case_id, progress) VALUES ('k', :c, 1.2)", c=case_id
    )
    await expect_db_error(
        conn, "INSERT INTO jobs (kind, case_id, attempts) VALUES ('k', :c, -1)", c=case_id
    )


async def test_deleting_a_document_removes_its_jobs(
    conn: AsyncConnection, case_id: uuid.UUID
) -> None:
    document = await insert_document(conn, case_id)
    await conn.execute(
        sa.text(
            "INSERT INTO jobs (kind, case_id, document_id) VALUES ('document_processing', :c, :d)"
        ),
        {"c": case_id, "d": document},
    )
    await conn.execute(sa.text("DELETE FROM documents WHERE id = :d"), {"d": document})
    assert await _scalar(conn, "SELECT count(*) FROM jobs WHERE case_id = :c", c=case_id) == 0


# --- deleting a case ---------------------------------------------------------------------


async def test_deleting_a_case_removes_its_data_but_not_its_audit_history(
    conn: AsyncConnection, case_id: uuid.UUID
) -> None:
    document = await insert_document(conn, case_id)
    page = await _page(conn, document)
    await _line(conn, document, page, "p1-L1")
    run = await _run(conn, document, active=True)
    await _field(conn, run, document)
    await conn.execute(
        sa.text(
            "INSERT INTO jobs (kind, case_id, document_id) VALUES ('document_processing', :c, :d)"
        ),
        {"c": case_id, "d": document},
    )
    await conn.execute(
        sa.text(
            "INSERT INTO audit_events (actor_id, role, case_id, action, entity_type, entity_id) "
            "VALUES (NULL, 'system', :c, 'case.deleted', 'case', :c)"
        ),
        {"c": case_id},
    )

    await conn.execute(sa.text("DELETE FROM cases WHERE id = :c"), {"c": case_id})

    for table in ("documents", "pages", "lines", "extraction_runs", "fields", "jobs"):
        remaining = await _scalar(conn, f"SELECT count(*) FROM {table}")
        assert remaining == 0, table
    audit = await _scalar(conn, "SELECT count(*) FROM audit_events WHERE case_id = :c", c=case_id)
    assert audit == 1

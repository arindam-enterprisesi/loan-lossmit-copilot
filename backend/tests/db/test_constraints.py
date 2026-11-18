"""Integrity rules the schema enforces itself."""

from __future__ import annotations

import uuid

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncConnection

from tests.db.conftest import expect_db_error, insert_document


async def _scalar(conn: AsyncConnection, sql: str, **params: object) -> object:
    return (await conn.execute(sa.text(sql), params)).scalar_one()


async def _page(conn: AsyncConnection, document_id: uuid.UUID, number: int = 1) -> uuid.UUID:
    result = await conn.execute(
        sa.text(
            "INSERT INTO pages (document_id, number, image_key, width, height) "
            "VALUES (:d, :n, 'p.png', 1000, 1400) RETURNING id"
        ),
        {"d": document_id, "n": number},
    )
    return result.scalar_one()


async def _line(
    conn: AsyncConnection, document_id: uuid.UUID, page_id: uuid.UUID, line_id: str
) -> None:
    await conn.execute(
        sa.text(
            "INSERT INTO lines (id, document_id, page_id, text, bbox, confidence) "
            "VALUES (:i, :d, :p, 'Net pay 2,033.61', "
            '\'{"x0": 0.1, "y0": 0.2, "x1": 0.5, "y1": 0.25}\', 0.98)'
        ),
        {"i": line_id, "d": document_id, "p": page_id},
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


# --- closed value sets -------------------------------------------------------------------


async def test_unknown_role_rejected(conn: AsyncConnection) -> None:
    await expect_db_error(
        conn,
        "INSERT INTO users (username, name, role, password_hash) VALUES ('x', 'X', 'boss', 'h')",
    )


async def test_unknown_pillar_rejected(conn: AsyncConnection, user_id: uuid.UUID) -> None:
    await expect_db_error(
        conn,
        "INSERT INTO cases (pillar, title, created_by) VALUES ('loan_processing', 'T', :u)",
        u=user_id,
    )


async def test_case_profile_starts_empty(conn: AsyncConnection, case_id: uuid.UUID) -> None:
    row = (
        await conn.execute(
            sa.text(
                "SELECT borrower_names, employment_type, reference_date, status "
                "FROM cases WHERE id = :c"
            ),
            {"c": case_id},
        )
    ).one()
    assert tuple(row) == (None, None, None, "open")


# --- documents ---------------------------------------------------------------------------


async def test_doc_type_is_free_text(conn: AsyncConnection, document_id: uuid.UUID) -> None:
    # Document types are administrator-managed configuration, so there is no CHECK.
    await conn.execute(
        sa.text("UPDATE documents SET doc_type = 'a_type_added_later' WHERE id = :d"),
        {"d": document_id},
    )


async def test_sha256_must_be_64_hex(conn: AsyncConnection, case_id: uuid.UUID) -> None:
    for bad in ("abc", "Z" * 64, "A" * 64):
        await expect_db_error(
            conn,
            "INSERT INTO documents (case_id, file_name, file_key, sha256, mime) "
            "VALUES (:c, 'a.pdf', 'k', :h, 'application/pdf')",
            c=case_id,
            h=bad,
        )


async def test_same_file_twice_in_a_case_is_allowed(
    conn: AsyncConnection, case_id: uuid.UUID
) -> None:
    # The FSD warns about duplicates ("Keep it anyway?"); it never blocks them.
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


async def test_page_numbers_unique_per_document(
    conn: AsyncConnection, document_id: uuid.UUID
) -> None:
    await _page(conn, document_id, 1)
    await _page(conn, document_id, 2)
    await expect_db_error(
        conn,
        "INSERT INTO pages (document_id, number, image_key, width, height) "
        "VALUES (:d, 1, 'again.png', 10, 10)",
        d=document_id,
    )


# --- lines -------------------------------------------------------------------------------


async def test_line_id_format(conn: AsyncConnection, document_id: uuid.UUID) -> None:
    page = await _page(conn, document_id)
    await _line(conn, document_id, page, "p1-L31")
    for bad in ("L31", "p1-31", "p1-L", "P1-L31", "p1-L31 "):
        await expect_db_error(
            conn,
            "INSERT INTO lines (id, document_id, page_id, text, bbox) "
            "VALUES (:i, :d, :p, 't', '{}')",
            i=bad,
            d=document_id,
            p=page,
        )


async def test_same_line_id_allowed_in_two_documents(
    conn: AsyncConnection, case_id: uuid.UUID
) -> None:
    first, second = await insert_document(conn, case_id), await insert_document(conn, case_id)
    await _line(conn, first, await _page(conn, first), "p1-L1")
    await _line(conn, second, await _page(conn, second), "p1-L1")
    await expect_db_error(
        conn,
        "INSERT INTO lines (id, document_id, page_id, text, bbox) "
        "SELECT 'p1-L1', document_id, page_id, 'dup', '{}' FROM lines WHERE document_id = :d",
        d=first,
    )


async def test_line_confidence_must_be_a_fraction(
    conn: AsyncConnection, document_id: uuid.UUID
) -> None:
    page = await _page(conn, document_id)
    await expect_db_error(
        conn,
        "INSERT INTO lines (id, document_id, page_id, text, bbox, confidence) "
        "VALUES ('p1-L2', :d, :p, 't', '{}', 1.5)",
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
            sa.text("SELECT review_status, version, line_ids, flags FROM fields WHERE run_id = :r"),
            {"r": run},
        )
    ).one()
    assert tuple(row) == ("unreviewed", 1, [], [])


# --- jobs --------------------------------------------------------------------------------


async def test_job_progress_range_and_defaults(conn: AsyncConnection, case_id: uuid.UUID) -> None:
    row = (
        await conn.execute(
            sa.text(
                "INSERT INTO jobs (kind, case_id) VALUES ('document_processing', :c) "
                "RETURNING status, progress"
            ),
            {"c": case_id},
        )
    ).one()
    assert tuple(row) == ("queued", 0.0)
    await expect_db_error(
        conn, "INSERT INTO jobs (kind, case_id, progress) VALUES ('k', :c, 1.2)", c=case_id
    )


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
        sa.text("INSERT INTO jobs (kind, case_id) VALUES ('document_processing', :c)"),
        {"c": case_id},
    )
    await conn.execute(
        sa.text(
            "INSERT INTO audit_events (actor, case_id, action, entity) "
            "VALUES ('system', :c, 'case.deleted', 'case')"
        ),
        {"c": case_id},
    )

    await conn.execute(sa.text("DELETE FROM cases WHERE id = :c"), {"c": case_id})

    for table in ("documents", "pages", "lines", "extraction_runs", "fields", "jobs"):
        remaining = await _scalar(conn, f"SELECT count(*) FROM {table}")
        assert remaining == 0, table
    audit = await _scalar(conn, "SELECT count(*) FROM audit_events WHERE case_id = :c", c=case_id)
    assert audit == 1

"""The D5 table (migration 0006): ``hardship_profiles``, a hardship letter read into a profile.

A profile is what the borrower says, with each item's quote and the line IDs it came from
(CLAUDE.md rule 2). A person confirms it later; the system never decides anything here.
"""

from __future__ import annotations

import json
import uuid

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncConnection

from tests.db.conftest import expect_db_error, insert_document

ITEM = {"quote": "I want to keep my home", "lines": ["p1-L14"], "verified": True}

INSERT = (
    "INSERT INTO hardship_profiles (run_id, case_id, primary_reason, onset, duration, intent) "
    "VALUES (:r, :c, CAST(:i AS jsonb), CAST(:i AS jsonb), CAST(:i AS jsonb), CAST(:i AS jsonb)) "
    "RETURNING id"
)


async def _run(conn: AsyncConnection, case_id: uuid.UUID) -> uuid.UUID:
    result = await conn.execute(
        sa.text(
            "INSERT INTO analysis_runs (case_id, feature) VALUES (:c, 'hardship') RETURNING id"
        ),
        {"c": case_id},
    )
    return result.scalar_one()


async def _profile(conn: AsyncConnection, case_id: uuid.UUID) -> uuid.UUID:
    result = await conn.execute(
        sa.text(INSERT), {"r": await _run(conn, case_id), "c": case_id, "i": json.dumps(ITEM)}
    )
    return result.scalar_one()


async def _columns(conn: AsyncConnection) -> dict[str, sa.Row[tuple[str, str, str]]]:
    rows = await conn.execute(
        sa.text(
            "SELECT column_name, data_type, is_nullable FROM information_schema.columns "
            "WHERE table_schema = 'public' AND table_name = 'hardship_profiles'"
        )
    )
    return {r.column_name: r for r in rows}


async def test_the_table_has_the_schema_docs_columns_and_three_that_keep_the_whole_profile(
    conn: AsyncConnection,
) -> None:
    doc = (
        "id run_id case_id primary_reason reasons onset duration intent timeline confirmed_by "
        "confirmed_at created_at"
    )
    # document_id: the letter the line IDs belong to (a line ID is only unique within a document).
    # enclosed_documents: part of Arindam's profile. source: a seeded sample or a model's reading.
    extra = "document_id enclosed_documents source"
    assert set(await _columns(conn)) == set(doc.split()) | set(extra.split())


async def test_each_part_of_the_profile_is_jsonb_and_required(conn: AsyncConnection) -> None:
    columns = await _columns(conn)
    for name in (
        "primary_reason",
        "reasons",
        "onset",
        "duration",
        "intent",
        "timeline",
        "enclosed_documents",
    ):
        assert columns[name].data_type == "jsonb", name
        assert columns[name].is_nullable == "NO", name
    for name in ("confirmed_by", "confirmed_at", "document_id"):
        assert columns[name].is_nullable == "YES", name  # none until a person confirms


async def test_a_new_profile_starts_unconfirmed_with_empty_lists(
    conn: AsyncConnection, case_id: uuid.UUID
) -> None:
    profile = await _profile(conn, case_id)

    row = (
        await conn.execute(
            sa.text(
                "SELECT reasons, timeline, enclosed_documents, source, confirmed_by, confirmed_at, "
                "document_id FROM hardship_profiles WHERE id = :p"
            ),
            {"p": profile},
        )
    ).one()

    assert row.reasons == [] and row.timeline == [] and row.enclosed_documents == []
    assert row.source == "model"
    assert (row.confirmed_by, row.confirmed_at, row.document_id) == (None, None, None)


async def test_the_source_is_a_closed_set(conn: AsyncConnection, case_id: uuid.UUID) -> None:
    profile = await _profile(conn, case_id)
    for good in ("seeded_sample", "model"):
        await conn.execute(
            sa.text("UPDATE hardship_profiles SET source = :s WHERE id = :p"),
            {"s": good, "p": profile},
        )
    await expect_db_error(
        conn, "UPDATE hardship_profiles SET source = 'guess' WHERE id = :p", p=profile
    )


async def test_one_profile_per_run(conn: AsyncConnection, case_id: uuid.UUID) -> None:
    run = await _run(conn, case_id)
    await conn.execute(sa.text(INSERT), {"r": run, "c": case_id, "i": json.dumps(ITEM)})

    await expect_db_error(conn, INSERT, r=run, c=case_id, i=json.dumps(ITEM))


async def test_a_profile_needs_its_run_and_its_case(
    conn: AsyncConnection, case_id: uuid.UUID
) -> None:
    await expect_db_error(conn, INSERT, r=uuid.uuid4(), c=case_id, i=json.dumps(ITEM))
    run = await _run(conn, case_id)
    await expect_db_error(conn, INSERT, r=run, c=uuid.uuid4(), i=json.dumps(ITEM))


async def test_deleting_a_case_removes_its_profiles(
    conn: AsyncConnection, case_id: uuid.UUID
) -> None:
    await _profile(conn, case_id)

    await conn.execute(sa.text("DELETE FROM cases WHERE id = :c"), {"c": case_id})

    count = (await conn.execute(sa.text("SELECT count(*) FROM hardship_profiles"))).scalar_one()
    assert count == 0


async def test_deleting_the_letter_keeps_the_profile_but_not_the_link(
    conn: AsyncConnection, case_id: uuid.UUID
) -> None:
    letter = await insert_document(conn, case_id)
    profile = await _profile(conn, case_id)
    await conn.execute(
        sa.text("UPDATE hardship_profiles SET document_id = :d WHERE id = :p"),
        {"d": letter, "p": profile},
    )

    await conn.execute(sa.text("DELETE FROM documents WHERE id = :d"), {"d": letter})

    row = (
        await conn.execute(
            sa.text("SELECT document_id FROM hardship_profiles WHERE id = :p"), {"p": profile}
        )
    ).one()
    assert row.document_id is None

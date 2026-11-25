"""The credit report tables (migration 0009): scores, tradelines and inquiries (Feature 4, D7).

Each row says which run and which document it came from and the report lines it was read from, so
every figure and flag links back to evidence (rule 2). The report is simulated, never a bureau's.
"""

from __future__ import annotations

import uuid

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncConnection

from tests.db.conftest import expect_db_error


async def _columns(conn: AsyncConnection, table: str) -> set[str]:
    rows = await conn.execute(
        sa.text(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_schema = 'public' AND table_name = :t"
        ),
        {"t": table},
    )
    return {r[0] for r in rows}


async def _run(conn: AsyncConnection, case_id: uuid.UUID) -> uuid.UUID:
    result = await conn.execute(
        sa.text("INSERT INTO analysis_runs (case_id, feature) VALUES (:c, 'credit') RETURNING id"),
        {"c": case_id},
    )
    return result.scalar_one()


async def _tradeline(
    conn: AsyncConnection, case_id: uuid.UUID, run: uuid.UUID, n: int = 1
) -> object:
    result = await conn.execute(
        sa.text(
            "INSERT INTO tradelines (run_id, case_id, position, creditor, account_type) "
            "VALUES (:r, :c, :n, 'Northgate Card', 'revolving') RETURNING id"
        ),
        {"r": run, "c": case_id, "n": n},
    )
    return result.scalar_one()


async def test_the_tables_have_the_schema_docs_columns_and_the_evidence_links(
    conn: AsyncConnection,
) -> None:
    expected = {
        "credit_scores": (
            "id run_id case_id document_id bureau score is_representative line_refs created_at"
        ),
        "tradelines": (
            "id run_id case_id document_id position creditor account_type ownership opened_on "
            "status balance credit_limit monthly_payment past_due late_30 late_60 late_90 "
            "last_late_on remarks line_refs utilization_over_review_level late_in_lookback "
            "derogatory created_at"
        ),
        "credit_inquiries": (
            "id run_id case_id document_id position creditor inquired_on in_window "
            "matched_tradeline_id line_refs created_at"
        ),
    }
    for table, columns in expected.items():
        assert await _columns(conn, table) == set(columns.split()), table


async def test_a_score_is_a_real_bureau_score_and_is_not_representative_unless_marked(
    conn: AsyncConnection, case_id: uuid.UUID
) -> None:
    run = await _run(conn, case_id)
    await conn.execute(
        sa.text(
            "INSERT INTO credit_scores (run_id, case_id, bureau, score) VALUES (:r, :c, 'A', 712)"
        ),
        {"r": run, "c": case_id},
    )
    row = (
        await conn.execute(sa.text("SELECT is_representative, line_refs FROM credit_scores"))
    ).one()
    assert row.is_representative is False and row.line_refs == []

    for bad in (299, 851):
        await expect_db_error(
            conn,
            "INSERT INTO credit_scores (run_id, case_id, bureau, score) VALUES (:r, :c, 'B', :s)",
            r=run,
            c=case_id,
            s=bad,
        )


async def test_a_tradeline_has_a_place_on_the_report_and_non_negative_late_counts(
    conn: AsyncConnection, case_id: uuid.UUID
) -> None:
    run = await _run(conn, case_id)
    await _tradeline(conn, case_id, run, 1)

    await expect_db_error(  # one row per place on the report
        conn,
        "INSERT INTO tradelines (run_id, case_id, position, creditor, account_type) "
        "VALUES (:r, :c, 1, 'Cardinal', 'revolving')",
        r=run,
        c=case_id,
    )
    await expect_db_error(
        conn,
        "INSERT INTO tradelines (run_id, case_id, position, creditor, account_type, late_30) "
        "VALUES (:r, :c, 2, 'Cardinal', 'revolving', -1)",
        r=run,
        c=case_id,
    )
    row = (
        await conn.execute(sa.text("SELECT late_30, late_60, late_90, derogatory FROM tradelines"))
    ).one()
    assert tuple(row) == (0, 0, 0, False)


async def test_an_inquiry_may_point_at_the_account_it_matched_and_survives_its_removal(
    conn: AsyncConnection, case_id: uuid.UUID
) -> None:
    run = await _run(conn, case_id)
    tradeline = await _tradeline(conn, case_id, run)
    await conn.execute(
        sa.text(
            "INSERT INTO credit_inquiries "
            "(run_id, case_id, position, creditor, matched_tradeline_id) "
            "VALUES (:r, :c, 1, 'Harbor Retail', :t)"
        ),
        {"r": run, "c": case_id, "t": tradeline},
    )

    await conn.execute(sa.text("DELETE FROM tradelines WHERE id = :t"), {"t": tradeline})

    row = (await conn.execute(sa.text("SELECT matched_tradeline_id FROM credit_inquiries"))).one()
    assert row.matched_tradeline_id is None


async def test_deleting_a_case_removes_its_credit_analysis(
    conn: AsyncConnection, case_id: uuid.UUID
) -> None:
    run = await _run(conn, case_id)
    await _tradeline(conn, case_id, run)
    await conn.execute(
        sa.text(
            "INSERT INTO credit_scores (run_id, case_id, bureau, score) VALUES (:r, :c, 'A', 700)"
        ),
        {"r": run, "c": case_id},
    )

    await conn.execute(sa.text("DELETE FROM cases WHERE id = :c"), {"c": case_id})

    for table in ("credit_scores", "tradelines", "credit_inquiries", "analysis_runs"):
        assert (await conn.execute(sa.text(f"SELECT count(*) FROM {table}"))).scalar_one() == 0

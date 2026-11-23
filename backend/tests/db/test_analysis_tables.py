"""The D4 tables (migration 0005): the schema doc's columns, closed value sets and links."""

from __future__ import annotations

import uuid

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncConnection

from tests.db.conftest import expect_db_error

FEATURES = (
    "income",
    "assets",
    "credit",
    "hardship",
    "underwriting",
    "lm_recommendation",
    "completeness",
)


async def _columns(conn: AsyncConnection, table: str) -> set[str]:
    rows = await conn.execute(
        sa.text(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_schema = 'public' AND table_name = :t"
        ),
        {"t": table},
    )
    return {r[0] for r in rows}


async def _run(conn: AsyncConnection, case_id: uuid.UUID, feature: str = "income") -> uuid.UUID:
    result = await conn.execute(
        sa.text("INSERT INTO analysis_runs (case_id, feature) VALUES (:c, :f) RETURNING id"),
        {"c": case_id, "f": feature},
    )
    return result.scalar_one()


# --- the doc's columns ----------------------------------------------------------------------


async def test_the_tables_have_the_schema_docs_columns(conn: AsyncConnection) -> None:
    config_versions = "id kind name version label source content_hash active created_at"
    assert await _columns(conn, "config_versions") == set(config_versions.split())
    analysis_runs = (
        "id case_id feature status job_id config_versions started_at finished_at created_by "
        "created_at"
    )
    assert await _columns(conn, "analysis_runs") == set(analysis_runs.split())
    calculations = "id run_id case_id name value unit formula inputs working evidence created_at"
    assert await _columns(conn, "calculations") == set(calculations.split())
    completeness = "id run_id case_id items overall_status updated_by updated_at created_at"
    assert await _columns(conn, "completeness_results") == set(completeness.split())


async def test_income_components_have_the_docs_columns_and_three_that_keep_the_original(
    conn: AsyncConnection,
) -> None:
    doc = (
        "id run_id borrower employer component current_period ytd monthly included "
        "exclusion_reason calculation_id"
    )
    extra = (
        "original_included original_exclusion_reason review_reason updated_by updated_at created_at"
    )
    # original_*: a person's include or exclude never overwrites the system's decision (rule 6).
    assert await _columns(conn, "income_components") == set(doc.split()) | set(extra.split())


async def test_money_is_numeric_and_never_a_float(conn: AsyncConnection) -> None:
    rows = await conn.execute(
        sa.text(
            "SELECT table_name, column_name, data_type, numeric_precision, numeric_scale "
            "FROM information_schema.columns WHERE table_schema = 'public' "
            "AND ((table_name = 'income_components' AND column_name IN "
            "('current_period', 'ytd', 'monthly')) OR "
            "(table_name = 'calculations' AND column_name = 'value'))"
        )
    )
    found = {
        (r.table_name, r.column_name): (r.data_type, r.numeric_precision, r.numeric_scale)
        for r in rows
    }
    for column in ("current_period", "ytd", "monthly"):
        assert found[("income_components", column)] == ("numeric", 14, 2)
    assert found[("calculations", "value")] == ("numeric", 20, 6)


# --- closed value sets and links -------------------------------------------------------------


async def test_run_features_and_statuses_are_closed_sets(
    conn: AsyncConnection, case_id: uuid.UUID
) -> None:
    for feature in FEATURES:
        await _run(conn, case_id, feature)
    await expect_db_error(
        conn, "INSERT INTO analysis_runs (case_id, feature) VALUES (:c, 'budget')", c=case_id
    )
    run = await _run(conn, case_id)
    for good in ("queued", "running", "succeeded", "failed"):
        await conn.execute(
            sa.text("UPDATE analysis_runs SET status = :s WHERE id = :r"), {"s": good, "r": run}
        )
    await expect_db_error(conn, "UPDATE analysis_runs SET status = 'done' WHERE id = :r", r=run)


async def test_a_new_run_is_queued_with_empty_config_versions(
    conn: AsyncConnection, case_id: uuid.UUID
) -> None:
    run = await _run(conn, case_id)
    row = (
        await conn.execute(
            sa.text("SELECT status, config_versions, finished_at FROM analysis_runs WHERE id = :r"),
            {"r": run},
        )
    ).one()
    assert (row.status, row.config_versions, row.finished_at) == ("queued", {}, None)


async def test_config_versions_kinds_labels_and_identity(conn: AsyncConnection) -> None:
    insert = (
        "INSERT INTO config_versions (kind, name, version, label, content_hash) "
        "VALUES (:k, 'income_method', '2026-11-19.1', :l, :h)"
    )
    await conn.execute(sa.text(insert), {"k": "income_method", "l": "illustrative", "h": "a" * 64})
    # The same file content is one row, however many runs used it.
    await expect_db_error(conn, insert, k="income_method", l="illustrative", h="a" * 64)
    # An edited file under the same version label is a different row (the label proves nothing).
    await conn.execute(sa.text(insert), {"k": "income_method", "l": "illustrative", "h": "b" * 64})
    await expect_db_error(conn, insert, k="settings", l="illustrative", h="c" * 64)
    await expect_db_error(conn, insert, k="checklist", l="sample", h="d" * 64)


async def test_an_excluded_component_must_carry_its_reason(
    conn: AsyncConnection, case_id: uuid.UUID
) -> None:
    run = await _run(conn, case_id)
    insert = (
        "INSERT INTO income_components (run_id, borrower, component, monthly, included, "
        "exclusion_reason, original_included) VALUES (:r, 'Daniel Reyes', :c, 444.41, :i, :why, :i)"
    )
    await conn.execute(sa.text(insert), {"r": run, "c": "base", "i": True, "why": None})
    reason = "history covers 2026 only"
    await conn.execute(sa.text(insert), {"r": run, "c": "overtime", "i": False, "why": reason})
    await expect_db_error(conn, insert, r=run, c="bonus", i=False, why=None)
    await expect_db_error(conn, insert, r=run, c="tips", i=True, why=None)  # not a component kind


async def test_a_calculation_keeps_its_working(conn: AsyncConnection, case_id: uuid.UUID) -> None:
    run = await _run(conn, case_id)
    await conn.execute(
        sa.text(
            "INSERT INTO calculations (run_id, case_id, name, value, unit, formula, inputs, "
            "working) VALUES (:r, :c, 'base_monthly', 5980.00, 'usd', "
            "'rate x hours x periods / 12', CAST(:i AS jsonb), "
            "'34.50 x 80.00 x 26 / 12 = 5,980.00')"
        ),
        {"r": run, "c": case_id, "i": '{"rate": "34.50", "hours": "80.00", "periods": "26"}'},
    )
    row = (await conn.execute(sa.text("SELECT value, unit, inputs FROM calculations"))).one()
    assert str(row.value) == "5980.000000" and row.inputs["rate"] == "34.50"


async def test_one_completeness_result_per_run_with_closed_overall_values(
    conn: AsyncConnection, case_id: uuid.UUID
) -> None:
    insert = (
        "INSERT INTO completeness_results (run_id, case_id, items, overall_status) "
        "VALUES (:r, :c, CAST('[]' AS jsonb), :o)"
    )
    first = await _run(conn, case_id, "completeness")
    await conn.execute(sa.text(insert), {"r": first, "c": case_id, "o": "incomplete"})
    await expect_db_error(conn, insert, r=first, c=case_id, o="complete")  # a second for the run
    for overall in ("complete", "needs_review"):
        run = await _run(conn, case_id, "completeness")
        await conn.execute(sa.text(insert), {"r": run, "c": case_id, "o": overall})
    await expect_db_error(
        conn, insert, r=await _run(conn, case_id, "completeness"), c=case_id, o="done"
    )


async def test_deleting_a_case_removes_its_runs_and_everything_under_them(
    conn: AsyncConnection, case_id: uuid.UUID
) -> None:
    run = await _run(conn, case_id)
    await conn.execute(
        sa.text(
            "INSERT INTO calculations (run_id, case_id, name, value, unit, formula, inputs, "
            "working) VALUES (:r, :c, 'x', 1, 'usd', 'f', '{}'::jsonb, 'w')"
        ),
        {"r": run, "c": case_id},
    )
    await conn.execute(
        sa.text(
            "INSERT INTO income_components (run_id, borrower, component, monthly, included, "
            "original_included) VALUES (:r, 'b', 'base', 1, true, true)"
        ),
        {"r": run},
    )
    await conn.execute(sa.text("DELETE FROM cases WHERE id = :c"), {"c": case_id})
    for table in ("analysis_runs", "calculations", "income_components"):
        assert (await conn.execute(sa.text(f"SELECT count(*) FROM {table}"))).scalar_one() == 0

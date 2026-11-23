"""The D6 shared tables (migration 0008): reports, findings, conditions, sign-offs, agent runs, the
waterfall and the lender view, as docs/database-schema.md lists them.

A sign-off records that a person reviewed a report; a condition keeps the text the agents wrote
beside the reviewer's edit; a waterfall option keeps what the rules decided beside an override.
Nothing here says anything is approved or denied (rule 3).
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


async def _run(
    conn: AsyncConnection, case_id: uuid.UUID, feature: str = "underwriting"
) -> uuid.UUID:
    result = await conn.execute(
        sa.text("INSERT INTO analysis_runs (case_id, feature) VALUES (:c, :f) RETURNING id"),
        {"c": case_id, "f": feature},
    )
    return result.scalar_one()


async def _report(
    conn: AsyncConnection, case_id: uuid.UUID, kind: str = "underwriting", version: int = 1
) -> uuid.UUID:
    run = await _run(
        conn, case_id, "underwriting" if kind == "underwriting" else "lm_recommendation"
    )
    result = await conn.execute(
        sa.text(
            "INSERT INTO reports (run_id, case_id, kind, version) VALUES (:r, :c, :k, :v) "
            "RETURNING id"
        ),
        {"r": run, "c": case_id, "k": kind, "v": version},
    )
    return result.scalar_one()


# --- the doc's columns ----------------------------------------------------------------------


async def test_the_tables_have_the_schema_docs_columns(conn: AsyncConnection) -> None:
    expected = {
        "reports": (
            "id run_id case_id kind version sections guardrail_results status source created_at"
        ),
        "findings": "id report_id priority title detail evidence flag_id created_at",
        "conditions": (
            "id report_id position text priority source decision edited_text reason decided_by "
            "decided_at created_at"
        ),
        "sign_offs": "id report_id case_id report_version signed_by role signed_at note created_at",
        "agent_runs": (
            "id run_id agent attempt status provider model prompt_id output error started_at "
            "finished_at created_at"
        ),
        "waterfall_results": (
            "id run_id rule_set_version order_no option status original_status conditions "
            "overridden override_reason overridden_by overridden_at created_at"
        ),
        "lender_views": (
            "id run_id foreclosure_loss modification_cost advantage settings calculation_ids "
            "created_at"
        ),
    }
    for table, columns in expected.items():
        assert await _columns(conn, table) == set(columns.split()), table


# --- reports and findings -------------------------------------------------------------------


async def test_a_report_is_of_one_kind_and_starts_as_a_draft_from_the_agents(
    conn: AsyncConnection, case_id: uuid.UUID
) -> None:
    report = await _report(conn, case_id)

    row = (
        await conn.execute(
            sa.text(
                "SELECT status, source, sections, guardrail_results FROM reports WHERE id = :r"
            ),
            {"r": report},
        )
    ).one()

    assert (row.status, row.source) == ("draft", "agents")
    assert row.sections == {} and row.guardrail_results == {}
    for good in ("in_review", "signed_off", "draft"):
        await conn.execute(
            sa.text("UPDATE reports SET status = :s WHERE id = :r"), {"s": good, "r": report}
        )
    await expect_db_error(conn, "UPDATE reports SET status = 'approved' WHERE id = :r", r=report)
    await expect_db_error(conn, "UPDATE reports SET kind = 'loan_decision' WHERE id = :r", r=report)
    await expect_db_error(conn, "UPDATE reports SET source = 'guess' WHERE id = :r", r=report)


async def test_a_run_has_each_report_version_once(
    conn: AsyncConnection, case_id: uuid.UUID
) -> None:
    run = await _run(conn, case_id)
    insert = (
        "INSERT INTO reports (run_id, case_id, kind, version) VALUES (:r, :c, 'underwriting', :v)"
    )
    await conn.execute(sa.text(insert), {"r": run, "c": case_id, "v": 1})
    await conn.execute(sa.text(insert), {"r": run, "c": case_id, "v": 2})
    await expect_db_error(conn, insert, r=run, c=case_id, v=2)
    await expect_db_error(conn, insert, r=run, c=case_id, v=0)  # versions count from 1


async def test_a_finding_has_a_review_priority_and_may_point_at_a_flag(
    conn: AsyncConnection, case_id: uuid.UUID
) -> None:
    report = await _report(conn, case_id)
    insert = (
        "INSERT INTO findings (report_id, priority, title, detail) "
        "VALUES (:r, :p, 'Assets short of funds to close', 'Assets 9,226.32 against 36,500.00')"
    )
    for priority in ("significant", "attention", "information"):
        await conn.execute(sa.text(insert), {"r": report, "p": priority})
    # The priorities describe review order, not eligibility (Feature Design 6.5).
    await expect_db_error(conn, insert, r=report, p="eligible")
    await expect_db_error(conn, insert, r=uuid.uuid4(), p="attention")


async def test_deleting_a_case_removes_its_reports_and_everything_under_them(
    conn: AsyncConnection, case_id: uuid.UUID, user_id: uuid.UUID
) -> None:
    report = await _report(conn, case_id)
    await conn.execute(
        sa.text(
            "INSERT INTO findings (report_id, priority, title, detail) "
            "VALUES (:r, 'attention', 't', 'd')"
        ),
        {"r": report},
    )
    await conn.execute(
        sa.text(
            "INSERT INTO conditions (report_id, text, priority, source) "
            "VALUES (:r, 't', 'attention', 'agent')"
        ),
        {"r": report},
    )
    await conn.execute(
        sa.text(
            "INSERT INTO sign_offs (report_id, case_id, report_version, signed_by, role) "
            "VALUES (:r, :c, 1, :u, 'underwriter')"
        ),
        {"r": report, "c": case_id, "u": user_id},
    )

    await conn.execute(sa.text("DELETE FROM cases WHERE id = :c"), {"c": case_id})

    for table in ("reports", "findings", "conditions", "sign_offs", "analysis_runs"):
        assert (await conn.execute(sa.text(f"SELECT count(*) FROM {table}"))).scalar_one() == 0


# --- conditions -----------------------------------------------------------------------------


async def test_a_condition_starts_pending_and_a_decision_needs_who_when_and_why(
    conn: AsyncConnection, case_id: uuid.UUID, user_id: uuid.UUID
) -> None:
    report = await _report(conn, case_id)
    condition = (
        await conn.execute(
            sa.text(
                "INSERT INTO conditions (report_id, text, priority, source) "
                "VALUES (:r, 'Document the 2,000.00 transfer', 'significant', 'agent') "
                "RETURNING id"
            ),
            {"r": report},
        )
    ).scalar_one()
    row = (
        await conn.execute(
            sa.text("SELECT decision, edited_text, decided_by FROM conditions WHERE id = :c"),
            {"c": condition},
        )
    ).one()
    assert (row.decision, row.edited_text, row.decided_by) == ("pending", None, None)

    decide = (
        "UPDATE conditions SET decision = :d, edited_text = :e, reason = :why, decided_by = :u, "
        "decided_at = now() WHERE id = :c"
    )
    # Accepted, edited (with the edit and a reason), rejected (with a reason): all recorded.
    for decision, edited, why in (
        ("accepted", None, "agree"),
        ("edited", "Document the 2,000.00 transfer with a gift letter", "wording"),
        ("rejected", None, "not required for this file"),
    ):
        await conn.execute(
            sa.text(decide), {"d": decision, "e": edited, "why": why, "u": user_id, "c": condition}
        )
    await expect_db_error(  # a decision with nobody behind it
        conn, decide, d="accepted", e=None, why="x", u=None, c=condition
    )
    await expect_db_error(  # an edit with no edited text
        conn, decide, d="edited", e=None, why="x", u=user_id, c=condition
    )
    await expect_db_error(  # a rejection with no reason
        conn, decide, d="rejected", e=None, why=None, u=user_id, c=condition
    )
    await expect_db_error(conn, decide, d="approved", e=None, why="x", u=user_id, c=condition)


async def test_a_conditions_source_and_priority_are_closed_sets(
    conn: AsyncConnection, case_id: uuid.UUID
) -> None:
    report = await _report(conn, case_id)
    insert = "INSERT INTO conditions (report_id, text, priority, source) VALUES (:r, 't', :p, :s)"
    await conn.execute(sa.text(insert), {"r": report, "p": "attention", "s": "user"})
    await expect_db_error(conn, insert, r=report, p="urgent", s="agent")
    await expect_db_error(conn, insert, r=report, p="attention", s="robot")


# --- sign-offs ------------------------------------------------------------------------------


async def test_a_sign_off_records_who_reviewed_which_version_and_when(
    conn: AsyncConnection, case_id: uuid.UUID, user_id: uuid.UUID
) -> None:
    report = await _report(conn, case_id)
    insert = (
        "INSERT INTO sign_offs (report_id, case_id, report_version, signed_by, role, note) "
        "VALUES (:r, :c, 1, :u, :role, 'reviewed')"
    )
    await conn.execute(
        sa.text(insert), {"r": report, "c": case_id, "u": user_id, "role": "underwriter"}
    )
    row = (await conn.execute(sa.text("SELECT signed_at FROM sign_offs"))).one()
    assert row.signed_at is not None  # when they reviewed it
    await expect_db_error(conn, insert, r=report, c=case_id, u=None, role="underwriter")
    await expect_db_error(conn, insert, r=report, c=case_id, u=user_id, role="approver")


# --- agent runs -----------------------------------------------------------------------------


async def test_an_agent_attempt_is_one_row_and_the_agents_are_a_closed_set(
    conn: AsyncConnection, case_id: uuid.UUID
) -> None:
    run = await _run(conn, case_id)
    insert = "INSERT INTO agent_runs (run_id, agent, attempt, status) VALUES (:r, :a, :n, :s)"
    for agent in ("researcher", "writer", "critic"):
        await conn.execute(sa.text(insert), {"r": run, "a": agent, "n": 1, "s": "succeeded"})
    await conn.execute(sa.text(insert), {"r": run, "a": "writer", "n": 2, "s": "failed"})  # a retry
    await expect_db_error(conn, insert, r=run, a="writer", n=2, s="failed")  # not twice
    await expect_db_error(conn, insert, r=run, a="planner", n=1, s="queued")
    await expect_db_error(conn, insert, r=run, a="critic", n=2, s="done")
    await expect_db_error(conn, insert, r=run, a="critic", n=0, s="queued")


# --- the waterfall and the lender view ------------------------------------------------------


async def test_each_option_of_a_run_has_one_result_with_the_five_statuses(
    conn: AsyncConnection, case_id: uuid.UUID
) -> None:
    run = await _run(conn, case_id, "lm_recommendation")
    insert = (
        "INSERT INTO waterfall_results (run_id, rule_set_version, order_no, option, status, "
        "original_status) VALUES (:r, 'sample-investor-a@1', :n, :o, :s, :s)"
    )
    options = (
        ("repayment_plan", "not_met"),
        ("forbearance", "not_met"),
        ("payment_deferral", "not_met"),
        ("loan_modification", "met"),
        ("short_sale", "not_reached"),
        ("deed_in_lieu", "needs_confirmation"),
    )
    for number, (option, status) in enumerate(options, start=1):
        await conn.execute(sa.text(insert), {"r": run, "n": number, "o": option, "s": status})
    await expect_db_error(conn, insert, r=run, n=9, o="loan_modification", s="met")  # a repeat
    await expect_db_error(conn, insert, r=run, n=9, o="trial_plan", s="met")
    await expect_db_error(conn, insert, r=run, n=9, o="short_sale", s="approved")


async def test_an_override_keeps_what_the_rules_decided_and_needs_a_reason(
    conn: AsyncConnection, case_id: uuid.UUID, user_id: uuid.UUID
) -> None:
    run = await _run(conn, case_id, "lm_recommendation")
    result = await conn.execute(
        sa.text(
            "INSERT INTO waterfall_results (run_id, rule_set_version, order_no, option, status, "
            "original_status) VALUES (:r, 'v', 1, 'forbearance', 'not_met', 'not_met') RETURNING id"
        ),
        {"r": run},
    )
    result_id = result.scalar_one()
    row = (
        await conn.execute(
            sa.text(
                "SELECT overridden, override_reason, overridden_by, conditions "
                "FROM waterfall_results"
            )
        )
    ).one()
    assert (row.overridden, row.override_reason, row.overridden_by) == (False, None, None)
    assert row.conditions == []

    override = (
        "UPDATE waterfall_results SET overridden = true, status = 'met', override_reason = :why, "
        "overridden_by = :u, overridden_at = now() WHERE id = :i"
    )
    await conn.execute(
        sa.text(override),
        {"why": "hardship is temporary per the borrower", "u": user_id, "i": result_id},
    )
    kept = (
        await conn.execute(sa.text("SELECT status, original_status FROM waterfall_results"))
    ).one()
    assert (kept.status, kept.original_status) == ("met", "not_met")  # both are on record
    await expect_db_error(conn, override, why=None, u=user_id, i=result_id)  # no reason
    await expect_db_error(conn, override, why="x", u=None, i=result_id)  # nobody behind it


async def test_a_run_has_one_lender_view_and_it_keeps_its_working(
    conn: AsyncConnection, case_id: uuid.UUID
) -> None:
    run = await _run(conn, case_id, "lm_recommendation")
    insert = (
        "INSERT INTO lender_views (run_id, foreclosure_loss, modification_cost, advantage, "
        "settings, calculation_ids) VALUES (:r, 16310.00, 13893.00, 2417.00, "
        "CAST('{}' AS jsonb), ARRAY[CAST(:c AS uuid)])"
    )
    await conn.execute(sa.text(insert), {"r": run, "c": str(uuid.uuid4())})
    await expect_db_error(conn, insert, r=run, c=str(uuid.uuid4()))
    row = (
        await conn.execute(
            sa.text("SELECT advantage, calculation_ids FROM lender_views WHERE run_id = :r"),
            {"r": run},
        )
    ).one()
    assert str(row.advantage) == "2417.00" and len(row.calculation_ids) == 1

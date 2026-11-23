"""The D6 feature tables (migration 0007): the schema doc's columns, value sets and links.

``loan_scenarios`` and ``loan_records`` hold what is entered or simulated for a case;
``transactions`` holds the labelled lines of each bank statement; ``obligations`` and
``budget_lines`` are results of a run. Where a person can change a value, the system's own value is
kept beside it (rule 6).
"""

from __future__ import annotations

import uuid
from datetime import date

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncConnection

from app.db.enums import TransactionCategory
from tests.db.conftest import expect_db_error, insert_document

CATEGORIES = [c.value for c in TransactionCategory]


async def _columns(conn: AsyncConnection, table: str) -> set[str]:
    rows = await conn.execute(
        sa.text(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_schema = 'public' AND table_name = :t"
        ),
        {"t": table},
    )
    return {r[0] for r in rows}


async def _run(conn: AsyncConnection, case_id: uuid.UUID, feature: str = "assets") -> uuid.UUID:
    result = await conn.execute(
        sa.text("INSERT INTO analysis_runs (case_id, feature) VALUES (:c, :f) RETURNING id"),
        {"c": case_id, "f": feature},
    )
    return result.scalar_one()


# --- the doc's columns ----------------------------------------------------------------------


async def test_the_tables_have_the_schema_docs_columns(conn: AsyncConnection) -> None:
    scenario = (
        "case_id purpose occupancy property_value loan_amount proposed_housing_payment "
        "funds_to_close created_by updated_by updated_at created_at"
    )
    assert await _columns(conn, "loan_scenarios") == set(scenario.split())
    record = (
        "id case_id loan_id investor unpaid_balance monthly_payment principal_interest escrow "
        "next_due_date months_delinquent arrears_amount source created_at"
    )
    assert await _columns(conn, "loan_records") == set(record.split())


async def test_transactions_have_the_docs_columns_and_the_ones_that_keep_the_original(
    conn: AsyncConnection,
) -> None:
    doc = (
        "id document_id line_ref account_last4 posted_on description amount direction category "
        "counterparty category_source payroll_match_field_id sourced_note"
    )
    # original_category: what the system labelled, kept when a person reclassifies (rule 6);
    # needs_review: the labeller left it "other"; sourced: a person marked a deposit as sourced.
    extra = "original_category needs_review sourced review_reason updated_by updated_at created_at"
    assert await _columns(conn, "transactions") == set(doc.split()) | set(extra.split())


async def test_obligations_and_budget_lines_have_the_docs_columns_and_the_audit_ones(
    conn: AsyncConnection,
) -> None:
    obligations = (
        "id run_id case_id creditor kind monthly_payment balance source counts_toward_dti reason"
    )
    obligations_extra = "original_counts_toward_dti review_reason updated_by updated_at created_at"
    assert await _columns(conn, "obligations") == set(obligations.split()) | set(
        obligations_extra.split()
    )
    budget = "id run_id category stated_amount observed_amount adjusted_amount adjustment_reason"
    assert await _columns(conn, "budget_lines") == set(budget.split()) | set(
        ["flagged", "updated_by", "updated_at", "created_at"]
    )


async def test_money_is_numeric_with_two_places_and_never_a_float(conn: AsyncConnection) -> None:
    rows = await conn.execute(
        sa.text(
            "SELECT table_name, column_name, data_type, numeric_precision, numeric_scale "
            "FROM information_schema.columns WHERE table_schema = 'public' AND "
            "(table_name, column_name) IN ("
            "('loan_scenarios','property_value'), ('loan_scenarios','loan_amount'), "
            "('loan_scenarios','proposed_housing_payment'), ('loan_scenarios','funds_to_close'), "
            "('loan_records','unpaid_balance'), ('loan_records','arrears_amount'), "
            "('transactions','amount'), ('obligations','monthly_payment'), "
            "('budget_lines','stated_amount'), ('budget_lines','adjusted_amount'))"
        )
    )
    found = {
        (r.table_name, r.column_name): (r.data_type, r.numeric_precision, r.numeric_scale)
        for r in rows
    }
    assert len(found) == 10
    assert set(found.values()) == {("numeric", 14, 2)}


# --- loan_scenarios and loan_records --------------------------------------------------------


async def test_a_case_has_one_loan_scenario_and_it_is_keyed_by_the_case(
    conn: AsyncConnection, case_id: uuid.UUID
) -> None:
    insert = (
        "INSERT INTO loan_scenarios (case_id, purpose, occupancy, property_value, loan_amount, "
        "proposed_housing_payment, funds_to_close) "
        "VALUES (:c, 'purchase', 'primary residence', 400000.00, 360000.00, 1980.00, 36500.00)"
    )
    await conn.execute(sa.text(insert), {"c": case_id})
    await expect_db_error(conn, insert, c=case_id)  # a second one for the same case
    await expect_db_error(conn, insert, c=uuid.uuid4())  # a case that does not exist


async def test_a_loan_scenario_needs_sensible_amounts(
    conn: AsyncConnection, case_id: uuid.UUID
) -> None:
    template = (
        "INSERT INTO loan_scenarios (case_id, purpose, occupancy, property_value, loan_amount, "
        "proposed_housing_payment, funds_to_close) "
        "VALUES (:c, 'purchase', 'primary residence', :v, :l, :p, :f)"
    )
    await expect_db_error(conn, template, c=case_id, v=0, l=1, p=1, f=1)  # no value, no LTV
    await expect_db_error(conn, template, c=case_id, v=100, l=-1, p=1, f=1)
    await expect_db_error(conn, template, c=case_id, v=100, l=1, p=-1, f=1)
    await expect_db_error(conn, template, c=case_id, v=100, l=1, p=1, f=-1)


async def test_a_case_has_one_loan_record_and_it_is_synthetic(
    conn: AsyncConnection, case_id: uuid.UUID
) -> None:
    insert = (
        "INSERT INTO loan_records (case_id, loan_id, investor, unpaid_balance, monthly_payment, "
        "principal_interest, escrow, next_due_date, months_delinquent, arrears_amount) "
        "VALUES (:c, '8800412271', 'Sample Investor A', 212400.00, 1720.00, 1298.40, 421.60, "
        "'2026-11-01', 3, 5160.00)"
    )
    await conn.execute(sa.text(insert), {"c": case_id})
    row = (await conn.execute(sa.text("SELECT source FROM loan_records"))).one()
    assert row.source == "synthetic"  # simulated servicing data, never real
    await expect_db_error(conn, insert, c=case_id)  # one record per case
    await expect_db_error(
        conn, "UPDATE loan_records SET source = 'servicer' WHERE case_id = :c", c=case_id
    )
    await expect_db_error(
        conn, "UPDATE loan_records SET months_delinquent = -1 WHERE case_id = :c", c=case_id
    )


# --- transactions ---------------------------------------------------------------------------


async def _transaction(conn: AsyncConnection, document: uuid.UUID, **overrides: object) -> None:
    values = {
        "d": document,
        "ref": "p1-L14",
        "when": date(2026, 9, 22),
        "desc": "ZELLE FROM PATRICIA OWENS REF 8841",
        "amt": 2000,
        "dir": "credit",
        "cat": "transfer in",
    }
    values.update(overrides)
    await conn.execute(
        sa.text(
            "INSERT INTO transactions (document_id, line_ref, posted_on, description, amount, "
            "direction, category) VALUES (:d, :ref, :when, :desc, :amt, :dir, :cat)"
        ),
        values,
    )


def test_the_database_categories_are_the_labelling_tasks_categories() -> None:
    # The database layer does not import the prompts package, so its list is a copy. This keeps
    # the two from drifting: a label the model may return must be one the table accepts.
    from app.prompts.schemas.transactions import TransactionCategory as Labelled

    assert [c.value for c in Labelled] == CATEGORIES


async def test_the_category_list_is_the_feature_designs_fourteen(
    conn: AsyncConnection, case_id: uuid.UUID
) -> None:
    assert len(CATEGORIES) == 14 and "other" in CATEGORIES
    document = await insert_document(conn, case_id)
    for number, category in enumerate(CATEGORIES, start=1):
        await _transaction(conn, document, ref=f"p1-L{number}", cat=category)
    await expect_db_error(
        conn,
        "INSERT INTO transactions (document_id, line_ref, posted_on, description, amount, "
        "direction, category) VALUES (:d, 'p2-L1', '2026-09-01', 'x', 1, 'credit', 'gift')",
        d=document,
    )


async def test_a_new_transaction_is_labelled_by_the_system_and_unreviewed(
    conn: AsyncConnection, case_id: uuid.UUID
) -> None:
    document = await insert_document(conn, case_id)
    await _transaction(conn, document)

    row = (
        await conn.execute(
            sa.text(
                "SELECT category_source, original_category, needs_review, sourced, sourced_note, "
                "review_reason, updated_by FROM transactions"
            )
        )
    ).one()

    assert row.category_source == "ai"
    assert (row.original_category, row.needs_review, row.sourced) == (None, False, False)
    assert (row.sourced_note, row.review_reason, row.updated_by) == (None, None, None)


async def test_a_line_is_one_transaction_and_amounts_and_directions_are_checked(
    conn: AsyncConnection, case_id: uuid.UUID
) -> None:
    document = await insert_document(conn, case_id)
    await _transaction(conn, document)
    await expect_db_error(  # the same line twice
        conn,
        "INSERT INTO transactions (document_id, line_ref, posted_on, description, amount, "
        "direction, category) VALUES (:d, 'p1-L14', '2026-09-22', 'x', 1, 'credit', 'other')",
        d=document,
    )
    await expect_db_error(  # an amount is a size; the direction says which way it went
        conn,
        "INSERT INTO transactions (document_id, line_ref, posted_on, description, amount, "
        "direction, category) VALUES (:d, 'p1-L15', '2026-09-22', 'x', -5, 'debit', 'other')",
        d=document,
    )
    await expect_db_error(
        conn,
        "INSERT INTO transactions (document_id, line_ref, posted_on, description, amount, "
        "direction, category) VALUES (:d, 'p1-L16', '2026-09-22', 'x', 5, 'sideways', 'other')",
        d=document,
    )
    await expect_db_error(  # a line reference has a shape
        conn,
        "INSERT INTO transactions (document_id, line_ref, posted_on, description, amount, "
        "direction, category) VALUES (:d, 'line 3', '2026-09-22', 'x', 5, 'credit', 'other')",
        d=document,
    )


async def test_a_reclassification_keeps_what_the_system_decided(
    conn: AsyncConnection, case_id: uuid.UUID, user_id: uuid.UUID
) -> None:
    document = await insert_document(conn, case_id)
    await _transaction(conn, document, cat="other")

    await conn.execute(
        sa.text(
            "UPDATE transactions SET original_category = category, category = 'transfer in', "
            "category_source = 'user', review_reason = 'it is her sister', updated_by = :u, "
            "updated_at = now()"
        ),
        {"u": user_id},
    )

    row = (
        await conn.execute(
            sa.text("SELECT category, original_category, category_source FROM transactions")
        )
    ).one()
    assert (row.category, row.original_category, row.category_source) == (
        "transfer in",
        "other",
        "user",
    )
    await expect_db_error(conn, "UPDATE transactions SET category_source = 'guess'")
    await expect_db_error(conn, "UPDATE transactions SET original_category = 'gift'")


async def test_deleting_a_document_removes_its_transactions(
    conn: AsyncConnection, case_id: uuid.UUID
) -> None:
    document = await insert_document(conn, case_id)
    await _transaction(conn, document)

    await conn.execute(sa.text("DELETE FROM documents WHERE id = :d"), {"d": document})

    assert (await conn.execute(sa.text("SELECT count(*) FROM transactions"))).scalar_one() == 0


# --- obligations ----------------------------------------------------------------------------


async def test_an_obligation_names_its_source_and_always_has_a_reason(
    conn: AsyncConnection, case_id: uuid.UUID
) -> None:
    run = await _run(conn, case_id)
    insert = (
        "INSERT INTO obligations (run_id, case_id, creditor, kind, monthly_payment, balance, "
        "source, counts_toward_dti, reason, original_counts_toward_dti) "
        "VALUES (:r, :c, :cr, 'installment', :p, 14860.00, :s, true, :why, true)"
    )
    for source in ("bank", "credit_report", "both"):
        await conn.execute(
            sa.text(insert),
            {
                "r": run,
                "c": case_id,
                "cr": "Lakeshore Auto Finance",
                "p": 420,
                "s": source,
                "why": "w",
            },
        )
    await expect_db_error(conn, insert, r=run, c=case_id, cr="x", p=1, s="rumour", why="w")
    await expect_db_error(conn, insert, r=run, c=case_id, cr="x", p=-1, s="bank", why="w")
    await expect_db_error(conn, insert, r=run, c=case_id, cr="x", p=1, s="bank", why=None)


async def test_deleting_a_run_removes_its_obligations_and_budget_lines(
    conn: AsyncConnection, case_id: uuid.UUID
) -> None:
    run = await _run(conn, case_id)
    await conn.execute(
        sa.text(
            "INSERT INTO obligations (run_id, case_id, creditor, kind, monthly_payment, source, "
            "counts_toward_dti, reason, original_counts_toward_dti) "
            "VALUES (:r, :c, 'x', 'revolving', 40, 'bank', true, 'w', true)"
        ),
        {"r": run, "c": case_id},
    )
    await conn.execute(
        sa.text(
            "INSERT INTO budget_lines (run_id, category, stated_amount, observed_amount) "
            "VALUES (:r, 'Other', 200.00, 410.00)"
        ),
        {"r": run},
    )

    await conn.execute(sa.text("DELETE FROM analysis_runs WHERE id = :r"), {"r": run})

    for table in ("obligations", "budget_lines"):
        assert (await conn.execute(sa.text(f"SELECT count(*) FROM {table}"))).scalar_one() == 0


# --- budget_lines ---------------------------------------------------------------------------


async def test_a_budget_has_one_line_per_category_and_an_adjustment_needs_a_reason(
    conn: AsyncConnection, case_id: uuid.UUID
) -> None:
    run = await _run(conn, case_id, "hardship")
    insert = (
        "INSERT INTO budget_lines (run_id, category, stated_amount, observed_amount, "
        "adjusted_amount, adjustment_reason) VALUES (:r, :cat, 200.00, 410.00, :adj, :why)"
    )
    await conn.execute(sa.text(insert), {"r": run, "cat": "Other", "adj": None, "why": None})
    await expect_db_error(conn, insert, r=run, cat="Other", adj=None, why=None)  # same category
    await conn.execute(
        sa.text(insert), {"r": run, "cat": "Utilities", "adj": 310, "why": "one-off repair"}
    )
    # An adjusted figure with no reason is not allowed (Feature Design 7.2: "with a reason").
    await expect_db_error(conn, insert, r=run, cat="Food", adj=300, why=None)
    row = (
        await conn.execute(sa.text("SELECT flagged FROM budget_lines WHERE category = 'Other'"))
    ).one()
    assert row.flagged is False

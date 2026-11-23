"""Asset and liability analysis through the API, the worker and Postgres: Daniel Reyes (FD 3.8).

The documents are stored as the real reader leaves them (an active extraction run and its fields),
taken from the generated scenario. The statement lines are labelled by the keyword ``FakeLabeller``
(no model); the credit report's tradelines are seeded fields, because the reader's schema for that
document does not exist yet (docs/build-log.md). The figures must match the Feature Design to the
cent, a person's change must recalculate at once and keep the system's answer beside it, and every
change must be audited.
"""

from __future__ import annotations

import json
import re
import uuid
from datetime import date
from decimal import Decimal as D
from pathlib import Path
from typing import Any

import httpx
import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.enums import Role
from app.db.seed import case_id
from app.services import asset_runs
from app.services.assets import WhatIfChanges
from app.services.transaction_labels import FakeLabeller
from app.worker import run_asset_analysis, run_income_analysis
from tests.db.conftest import FakeQueue, auth_headers
from tests.db.test_income_api import seed_document
from tests.services.test_income import RETURN_2025, STUB, W2_2025

DANIEL = case_id("Daniel Reyes — purchase")
ANGELA = case_id("Angela Whitfield — hardship")
BASE = f"/api/v1/cases/{DANIEL}/asset-liability"
SCENARIO_URL = f"/api/v1/cases/{DANIEL}/loan-scenario"
DATA = json.loads(
    (Path(__file__).resolve().parents[3] / "data/synthetic/scenarios/daniel_reyes.json").read_text(
        encoding="utf-8"
    )
)
EXPECTED = DATA["expected"]["assets_liabilities"]
LOAN = DATA["loan_scenario"]
BLOCKED = re.compile(r"\b(approve[sd]?|deny|denied|offer(s|ed)?|eligible|qualifies)\b", re.I)
SCENARIO_BODY = {
    "purpose": LOAN["purpose"],
    "occupancy": LOAN["occupancy"],
    "property_value": LOAN["property_value"],
    "loan_amount": LOAN["loan_amount"],
    "proposed_housing_payment": LOAN["proposed_housing_payment"],
    "funds_to_close": LOAN["funds_needed_to_close"],
}
FIRST_LINE = 14


@pytest.fixture(autouse=True)
async def seeded(session: AsyncSession) -> None:
    from app.db.seed import seed

    await seed(session, "demo-pass")


def headers(role: Role = Role.UNDERWRITER) -> dict[str, str]:
    return auth_headers(role)


# --- seeding Daniel's documents --------------------------------------------------------------


async def seed_income_documents(session: AsyncSession, *, net_pay: str = "2,033.61") -> None:
    # The corrected net pay: the printed 2,083.61 does not match his deposits (demo step 3).
    await seed_document(session, DANIEL, "pay_stub", {**STUB, "net_pay_current": net_pay})
    await seed_document(session, DANIEL, "w2", W2_2025, minutes=1)
    await seed_document(session, DANIEL, "tax_return_1040", RETURN_2025, minutes=2)


async def seed_statements(session: AsyncSession, case: uuid.UUID = DANIEL) -> None:
    for minutes, doc in enumerate(d for d in DATA["documents"] if d["type"] == "bank_statement"):
        facts = doc["facts"]
        values = {
            "institution_name": facts["bank"],
            "account_holder": "Daniel Reyes",
            "account_last4": facts["account_last4"],
            "statement_period_start": facts["period_start"],
            "statement_period_end": facts["period_end"],
            "opening_balance": facts["opening_balance"],
            "closing_balance": facts["closing_balance"],
        }
        lines = {"closing_balance": "p3-L12"}
        for n, t in enumerate(facts["transactions"], start=1):
            ref = f"p1-L{FIRST_LINE + n}"
            for part, value in (
                ("date", t["date"]),
                ("description", t["description"]),
                ("amount", t["amount"]),
            ):
                values[f"txn_{n:03d}_{part}"] = value
                lines[f"txn_{n:03d}_{part}"] = ref
        await seed_document(
            session,
            case,
            "bank_statement",
            values,
            minutes=10 + minutes,
            lines=lines,
            period=(
                date.fromisoformat(facts["period_start"]),
                date.fromisoformat(facts["period_end"]),
            ),
        )


async def seed_credit_report(session: AsyncSession) -> None:
    values: dict[str, str] = {"consumer_name": "Daniel Reyes", "report_date": "2026-10-12"}
    lines: dict[str, str] = {}
    tradelines = next(d for d in DATA["documents"] if d["type"] == "credit_report")["facts"][
        "tradelines"
    ]
    for n, t in enumerate(tradelines, start=1):
        for part in ("creditor", "account_type", "balance", "credit_limit", "monthly_payment"):
            values[f"tradeline_{n:03d}_{part}"] = t[part]
            lines[f"tradeline_{n:03d}_{part}"] = f"p2-L{8 + n}"
    await seed_document(session, DANIEL, "credit_report", values, minutes=20, lines=lines)


async def seed_all(session: AsyncSession, *, credit_report: bool = True) -> None:
    await seed_income_documents(session)
    await seed_statements(session)
    if credit_report:
        await seed_credit_report(session)


# --- driving the endpoints -------------------------------------------------------------------


async def income_run(client: httpx.AsyncClient, factory: async_sessionmaker[AsyncSession]) -> None:
    response = await client.post(f"/api/v1/cases/{DANIEL}/income-analysis", headers=headers())
    accepted = response.json()
    await run_income_analysis(
        {"session_factory": factory}, accepted["job"]["id"], accepted["analysis_id"]
    )


async def enter_scenario(client: httpx.AsyncClient, **changes: Any) -> httpx.Response:
    return await client.put(SCENARIO_URL, json={**SCENARIO_BODY, **changes}, headers=headers())


async def start(client: httpx.AsyncClient, role: Role = Role.UNDERWRITER) -> httpx.Response:
    return await client.post(BASE, headers=headers(role))


async def work(
    accepted: dict[str, Any], factory: async_sessionmaker[AsyncSession], **ctx: Any
) -> None:
    context = {"session_factory": factory, "labeller": FakeLabeller(), **ctx}
    await run_asset_analysis(context, accepted["job"]["id"], accepted["analysis_id"])


async def analyse(
    client: httpx.AsyncClient, factory: async_sessionmaker[AsyncSession]
) -> dict[str, Any]:
    response = await start(client)
    assert response.status_code == 202, response.text
    accepted: dict[str, Any] = response.json()
    await work(accepted, factory)
    return accepted


async def latest(client: httpx.AsyncClient, role: Role = Role.UNDERWRITER) -> dict[str, Any]:
    response = await client.get(f"{BASE}/latest", headers=headers(role))
    assert response.status_code == 200, response.text
    return response.json()  # type: ignore[no-any-return]


async def daniel(
    client: httpx.AsyncClient,
    session: AsyncSession,
    factory: async_sessionmaker[AsyncSession],
    *,
    credit_report: bool = True,
) -> dict[str, Any]:
    """Everything in place and analysed: documents, income, the loan scenario, the asset run."""
    await seed_all(session, credit_report=credit_report)
    await income_run(client, factory)
    assert (await enter_scenario(client)).status_code == 200
    await analyse(client, factory)
    return await latest(client)


def value(analysis: dict[str, Any], name: str) -> str:
    return analysis[name]["value"]  # type: ignore[no-any-return]


def line(analysis: dict[str, Any], description: str) -> dict[str, Any]:
    return next(t for t in analysis["transactions"] if t["description"] == description)


def debt(analysis: dict[str, Any], creditor: str) -> dict[str, Any]:
    return next(o for o in analysis["obligations"] if o["creditor"] == creditor)


async def rows(session: AsyncSession, sql: str, **params: Any) -> list[Any]:
    return list((await session.execute(sa.text(sql), params)).all())


# --- the loan scenario -----------------------------------------------------------------------


async def test_the_loan_scenario_is_entered_read_back_and_replaced_with_the_old_values_audited(
    docs_client: httpx.AsyncClient, session: AsyncSession
) -> None:
    missing = await docs_client.get(SCENARIO_URL, headers=headers())
    assert missing.status_code == 404

    entered = await enter_scenario(docs_client)
    assert entered.status_code == 200
    assert entered.json()["loan_amount"] == "360000.00"
    assert (await docs_client.get(SCENARIO_URL, headers=headers())).json()["funds_to_close"] == (
        "36500.00"
    )

    await enter_scenario(docs_client, loan_amount="320000")
    assert (await docs_client.get(SCENARIO_URL, headers=headers())).json()["loan_amount"] == (
        "320000.00"
    )
    events = await rows(
        session,
        "SELECT action, before, after FROM audit_events "
        "WHERE entity_type = 'loan_scenario' ORDER BY id",
    )
    assert [e.action for e in events] == ["loan_scenario.entered", "loan_scenario.replaced"]
    assert events[1].before["loan_amount"] == "360000.00"
    assert events[1].after["loan_amount"] == "320000.00"


@pytest.mark.parametrize(
    "changes",
    [
        {"property_value": "0"},
        {"loan_amount": "-1"},
        {"funds_to_close": "-5.00"},
        {"purpose": ""},
        {"loan_amount": "1.234"},
        {"surprise": "x"},
    ],
)
async def test_an_unusable_loan_scenario_is_a_422(
    docs_client: httpx.AsyncClient, changes: dict[str, str]
) -> None:
    response = await enter_scenario(docs_client, **changes)

    assert response.status_code == 422


async def test_the_loan_scenario_is_hidden_from_a_role_that_cannot_see_the_case(
    docs_client: httpx.AsyncClient,
) -> None:
    lm = headers(Role.LM_SPECIALIST)

    assert (await docs_client.put(SCENARIO_URL, json=SCENARIO_BODY, headers=lm)).status_code == 404
    assert (await docs_client.get(SCENARIO_URL, headers=lm)).status_code == 404
    assert (await docs_client.get(SCENARIO_URL)).status_code == 401


# --- running it ------------------------------------------------------------------------------


async def test_running_queues_a_job_and_the_worker_stores_the_result(
    docs_client: httpx.AsyncClient,
    session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
    fake_queue: FakeQueue,
) -> None:
    await seed_all(session)
    response = await start(docs_client)

    assert response.status_code == 202
    accepted = response.json()
    assert accepted["job"]["kind"] == "asset_analysis" and accepted["job"]["status"] == "queued"
    assert fake_queue.calls == [
        (
            "run_asset_analysis",
            (accepted["job"]["id"], accepted["analysis_id"]),
            accepted["job"]["id"],
        )
    ]

    await work(accepted, session_factory)
    job = (await rows(session, "SELECT status, stage, progress, error FROM jobs"))[0]
    assert tuple(job) == ("succeeded", "done", 1.0, None)
    run = (await rows(session, "SELECT status, config_versions FROM analysis_runs"))[0]
    assert run.status == "succeeded" and "thresholds" in run.config_versions


async def test_the_latest_analysis_has_daniels_figures_to_the_cent(
    docs_client: httpx.AsyncClient,
    session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    analysis = await daniel(docs_client, session, session_factory)

    assert value(analysis, "documented_assets") == EXPECTED["documented_assets"] == "9226.32"
    assert value(analysis, "funds_shortfall") == EXPECTED["shortfall"] == "27273.68"
    assert value(analysis, "monthly_obligations") == EXPECTED["obligations_monthly"] == "693.00"
    assert analysis["front_end_ratio"]["working"] == "1,980.00 / 5,980.00 = 33.11%"
    assert analysis["dti"]["working"] == "(1,980.00 + 693.00) / 5,980.00 = 44.70%"
    assert analysis["ltv"]["working"] == "360,000.00 / 400,000.00 = 90.00%"
    other = {c["name"]: c for c in analysis["calculations"]}
    assert other["dti_with_overtime"]["working"] == "(1,980.00 + 693.00) / 6,424.41 = 41.61%"
    assert analysis["note"].endswith("They are not a decision.")


async def test_the_debts_are_five_counted_and_the_rent_is_not(
    docs_client: httpx.AsyncClient,
    session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    analysis = await daniel(docs_client, session, session_factory)

    counted = {
        o["creditor"]: o["monthly_payment"]
        for o in analysis["obligations"]
        if o["counts_toward_dti"]
    }
    assert counted == {
        "Lakeshore Auto Finance": "420.00",
        "Brightpath Student Loan Servicing": "110.00",
        "Northgate Card": "88.00",
        "Cardinal Rewards Visa": "40.00",
        "Harbor Retail Card": "35.00",
    }
    assert debt(analysis, "Harbor Retail Card")["source"] == "credit_report"
    assert debt(analysis, "Lakeshore Auto Finance")["source"] == "both"
    rent = debt(analysis, "Oakmont Apartments")
    assert rent["counts_toward_dti"] is False and "primary residence" in rent["reason"]
    assert all(o["change"] is None for o in analysis["obligations"])


async def test_each_line_carries_its_label_and_the_payroll_matches_and_the_large_deposit(
    docs_client: httpx.AsyncClient,
    session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    analysis = await daniel(docs_client, session, session_factory)

    transactions = analysis["transactions"]
    assert len(transactions) == sum(
        len(d["facts"]["transactions"]) for d in DATA["documents"] if d["type"] == "bank_statement"
    )
    rent = line(analysis, "OAKMONT APARTMENTS RENT")
    assert rent["category"] == rent["system_category"] == "housing payment"
    assert (rent["category_source"], rent["counterparty"]) == ("ai", "Oakmont Apartments")
    matched = {(t["posted_on"], t["amount"]) for t in transactions if t["payroll_match"]}
    for expected in EXPECTED["payroll_matches"]:
        assert (expected["date"], expected["amount"]) in matched
    large = [t for t in transactions if t["large_deposit"]]
    assert [(t["posted_on"], t["amount"], t["counterparty"]) for t in large] == [
        (
            EXPECTED["large_deposit"]["date"],
            EXPECTED["large_deposit"]["amount"],
            EXPECTED["large_deposit"]["counterparty"],
        )
    ]
    # The figure points at the statement line it came from (rule 2).
    refs = large[0]["large_deposit"]["evidence"][0]
    assert refs["document_id"] == large[0]["document_id"] and refs["line_ids"] == [
        large[0]["line_id"]
    ]
    match_refs = next(t for t in transactions if t["payroll_match"])["payroll_match"]["evidence"]
    assert match_refs[1]["field"] == "net_pay_current"


async def test_the_flags_are_the_shortfall_the_transfer_and_the_dti_review(
    docs_client: httpx.AsyncClient,
    session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    analysis = await daniel(docs_client, session, session_factory)

    by_code = {f["code"]: f for f in analysis["flags"]}
    assert sorted(c for c, f in by_code.items() if f["severity"] != "info") == [
        "AL-W101",
        "AL-W105",
        "AL-W106",
    ]
    assert by_code["AL-W106"]["message"] == "DTI 44.70% is above the review level of 43%."
    assert by_code["AL-W101"]["refs"][0]["line_ids"]
    assert all(f["status"] == "open" for f in analysis["flags"])


async def test_the_net_pay_that_does_not_match_the_deposits_says_so(
    docs_client: httpx.AsyncClient,
    session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await seed_income_documents(session, net_pay="2,083.61")  # as printed, uncorrected
    await seed_statements(session)
    await analyse(docs_client, session_factory)

    analysis = await latest(docs_client)

    assert not any(t["payroll_match"] for t in analysis["transactions"])
    assert [f["code"] for f in analysis["flags"]].count("AL-W104") == 4


async def test_without_a_credit_report_the_four_bank_debts_give_658_and_nothing_is_reconciled(
    docs_client: httpx.AsyncClient,
    session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    analysis = await daniel(docs_client, session, session_factory, credit_report=False)

    assert value(analysis, "monthly_obligations") == "658.00"
    assert analysis["dti"]["working"] == "(1,980.00 + 658.00) / 5,980.00 = 44.11%"
    assert "AL-W103" not in [f["code"] for f in analysis["flags"]]


async def test_with_no_loan_scenario_the_ratios_say_what_is_missing(
    docs_client: httpx.AsyncClient,
    session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await seed_all(session)
    await income_run(docs_client, session_factory)
    await analyse(docs_client, session_factory)

    analysis = await latest(docs_client)

    assert value(analysis, "documented_assets") == "9226.32"
    assert (
        analysis["dti"] is None and analysis["ltv"] is None and analysis["funds_shortfall"] is None
    )
    info = next(f for f in analysis["flags"] if f["code"] == "AL-I101")
    assert "loan scenario" in info["message"]


async def test_with_no_income_analysis_the_dti_says_what_is_missing(
    docs_client: httpx.AsyncClient,
    session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await seed_all(session)
    await enter_scenario(docs_client)
    await analyse(docs_client, session_factory)

    analysis = await latest(docs_client)

    assert analysis["ltv"]["working"].endswith("90.00%")
    assert analysis["dti"] is None
    assert any("candidate monthly income" in f["message"] for f in analysis["flags"])


async def test_running_it_again_keeps_every_label_and_a_second_run_is_history(
    docs_client: httpx.AsyncClient,
    session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    first = await daniel(docs_client, session, session_factory)

    class NeverCalled:
        async def label(self, *_: Any, **__: Any) -> Any:
            raise AssertionError("a line that is already labelled must not be labelled again")

    response = await start(docs_client)
    await work(response.json(), session_factory, labeller=NeverCalled())

    second = await latest(docs_client)
    assert second["id"] != first["id"]
    assert [t["id"] for t in second["transactions"]] == [t["id"] for t in first["transactions"]]
    assert value(second, "monthly_obligations") == "693.00"
    assert len(await rows(session, "SELECT id FROM analysis_runs WHERE feature = 'assets'")) == 2


# --- a person's changes ----------------------------------------------------------------------


async def test_marking_the_large_deposit_as_sourced_clears_its_flag_at_once_and_keeps_the_note(
    docs_client: httpx.AsyncClient,
    session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    analysis = await daniel(docs_client, session, session_factory)
    zelle = line(analysis, "ZELLE FROM PATRICIA OWENS REF 8841")

    response = await docs_client.patch(
        f"{BASE}/latest/transactions/{zelle['id']}",
        json={"sourced": True, "reason": "Gift letter from the borrower's aunt, seen 23 Nov."},
        headers=headers(),
    )

    assert response.status_code == 200, response.text
    after = response.json()
    assert "AL-W101" not in [f["code"] for f in after["flags"]]
    changed = line(after, "ZELLE FROM PATRICIA OWENS REF 8841")
    assert changed["sourced"] and changed["sourced_note"].startswith("Gift letter")
    assert changed["large_deposit"] is not None  # still a large deposit, now with a source noted
    assert changed["change"]["reason"].startswith("Gift letter")
    event = (
        await rows(
            session,
            "SELECT action, reason, before, after FROM audit_events "
            "WHERE action = 'assets.deposit_sourced'",
        )
    )[0]
    assert event.before["sourced"] is False and event.after["sourced"] is True
    assert event.reason.startswith("Gift letter")


async def test_a_sourced_mark_can_be_undone_and_the_flag_returns(
    docs_client: httpx.AsyncClient,
    session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    analysis = await daniel(docs_client, session, session_factory)
    zelle = line(analysis, "ZELLE FROM PATRICIA OWENS REF 8841")
    url = f"{BASE}/latest/transactions/{zelle['id']}"
    await docs_client.patch(url, json={"sourced": True, "reason": "seen"}, headers=headers())

    undone = await docs_client.patch(
        url, json={"sourced": False, "reason": "The letter was not signed."}, headers=headers()
    )

    assert "AL-W101" in [f["code"] for f in undone.json()["flags"]]
    assert line(undone.json(), "ZELLE FROM PATRICIA OWENS REF 8841")["sourced_note"] is None


async def test_reclassifying_a_line_recalculates_at_once_and_keeps_the_original_label(
    docs_client: httpx.AsyncClient,
    session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    analysis = await daniel(docs_client, session, session_factory)
    payment = line(analysis, "CARDINAL REWARDS VISA PMT")
    assert debt(analysis, "Cardinal Rewards Visa")["source"] == "both"

    response = await docs_client.patch(
        f"{BASE}/latest/transactions/{payment['id']}",
        json={"category": "everyday spending", "reason": "Not a card payment: a store purchase."},
        headers=headers(),
    )

    assert response.status_code == 200, response.text
    after = response.json()
    changed = next(t for t in after["transactions"] if t["id"] == payment["id"])
    assert (changed["category"], changed["system_category"]) == (
        "everyday spending",
        "credit card payment",
    )
    assert changed["category_source"] == "user" and changed["needs_review"] is False
    assert changed["change"]["reason"].startswith("Not a card payment")
    # Recalculated at once: the bank statements no longer show that payment, the report still does.
    assert debt(after, "Cardinal Rewards Visa")["source"] == "credit_report"
    assert value(after, "monthly_obligations") == "693.00"
    stored = (
        await rows(
            session,
            "SELECT category, original_category, category_source, updated_by FROM transactions "
            "WHERE id = :id",
            id=payment["id"],
        )
    )[0]
    assert (stored.category, stored.original_category, stored.category_source) == (
        "everyday spending",
        "credit card payment",
        "user",
    )
    assert stored.updated_by is not None
    event = (
        await rows(
            session,
            "SELECT before, after FROM audit_events "
            "WHERE action = 'assets.transaction_reclassified'",
        )
    )[0]
    assert event.before["category"] == "credit card payment"
    assert event.after["original_category"] == "credit card payment"


async def test_reclassifying_twice_keeps_the_first_systems_label_as_the_original(
    docs_client: httpx.AsyncClient,
    session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    analysis = await daniel(docs_client, session, session_factory)
    target = line(analysis, "TARGET T-1124")
    url = f"{BASE}/latest/transactions/{target['id']}"

    await docs_client.patch(
        url, json={"category": "everyday spending", "reason": "one"}, headers=headers()
    )
    final = await docs_client.patch(
        url, json={"category": "refund", "reason": "two"}, headers=headers()
    )

    changed = next(t for t in final.json()["transactions"] if t["id"] == target["id"])
    assert (changed["category"], changed["system_category"]) == ("refund", "other")
    assert changed["change"]["reason"] == "two"


async def test_excluding_a_debt_recalculates_the_dti_and_keeps_the_systems_decision(
    docs_client: httpx.AsyncClient,
    session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    analysis = await daniel(docs_client, session, session_factory)
    harbor = debt(analysis, "Harbor Retail Card")

    response = await docs_client.patch(
        f"{BASE}/latest/obligations/{harbor['id']}",
        json={"counts_toward_dti": False, "reason": "Paid off at closing, per the payoff letter."},
        headers=headers(),
    )

    assert response.status_code == 200, response.text
    after = response.json()
    assert value(after, "monthly_obligations") == "658.00"
    assert after["dti"]["working"] == "(1,980.00 + 658.00) / 5,980.00 = 44.11%"
    changed = debt(after, "Harbor Retail Card")
    assert changed["counts_toward_dti"] is False and changed["system_counts_toward_dti"] is True
    assert changed["change"]["reason"].startswith("Paid off")
    assert changed["id"] == harbor["id"]  # the debt keeps its id through the recalculation
    event = (
        await rows(
            session,
            "SELECT before, after, reason FROM audit_events "
            "WHERE action = 'assets.obligation_excluded'",
        )
    )[0]
    assert event.before["monthly_obligations"] == "693.00"
    assert event.after["monthly_obligations"] == "658.00"
    assert event.after["system_counts_toward_dti"] is True
    assert event.reason.startswith("Paid off")


async def test_including_the_rent_counts_it_and_including_it_again_changes_nothing_more(
    docs_client: httpx.AsyncClient,
    session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    analysis = await daniel(docs_client, session, session_factory)
    rent = debt(analysis, "Oakmont Apartments")

    response = await docs_client.patch(
        f"{BASE}/latest/obligations/{rent['id']}",
        json={"counts_toward_dti": True, "reason": "The lease runs past closing."},
        headers=headers(),
    )

    after = response.json()
    assert value(after, "monthly_obligations") == "2118.00"
    assert debt(after, "Oakmont Apartments")["system_counts_toward_dti"] is False


async def test_a_new_run_keeps_a_persons_exclusion_and_the_systems_original(
    docs_client: httpx.AsyncClient,
    session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    analysis = await daniel(docs_client, session, session_factory)
    harbor = debt(analysis, "Harbor Retail Card")
    await docs_client.patch(
        f"{BASE}/latest/obligations/{harbor['id']}",
        json={"counts_toward_dti": False, "reason": "Paid off at closing."},
        headers=headers(),
    )

    await analyse(docs_client, session_factory)

    again = await latest(docs_client)
    assert again["id"] != analysis["id"]
    carried = debt(again, "Harbor Retail Card")
    assert carried["counts_toward_dti"] is False and carried["system_counts_toward_dti"] is True
    assert carried["change"]["reason"] == "Paid off at closing."
    assert value(again, "monthly_obligations") == "658.00"


async def test_undoing_an_exclusion_clears_it_and_a_later_run_does_not_bring_it_back(
    docs_client: httpx.AsyncClient,
    session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    analysis = await daniel(docs_client, session, session_factory)
    harbor = debt(analysis, "Harbor Retail Card")
    url = f"{BASE}/latest/obligations/{harbor['id']}"
    await docs_client.patch(
        url, json={"counts_toward_dti": False, "reason": "paid off"}, headers=headers()
    )
    await docs_client.patch(
        url, json={"counts_toward_dti": True, "reason": "payoff fell through"}, headers=headers()
    )

    await analyse(docs_client, session_factory)

    again = await latest(docs_client)
    assert value(again, "monthly_obligations") == "693.00"
    assert debt(again, "Harbor Retail Card")["counts_toward_dti"] is True


# --- refusals --------------------------------------------------------------------------------


async def test_a_change_needs_exactly_one_thing_and_a_reason(
    docs_client: httpx.AsyncClient,
    session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    analysis = await daniel(docs_client, session, session_factory)
    zelle = line(analysis, "ZELLE FROM PATRICIA OWENS REF 8841")["id"]
    harbor = debt(analysis, "Harbor Retail Card")["id"]
    txn_url = f"{BASE}/latest/transactions/{zelle}"
    debt_url = f"{BASE}/latest/obligations/{harbor}"

    for body in (
        {"sourced": True},
        {"sourced": True, "reason": "   "},
        {"reason": "x"},
        {"category": "refund", "sourced": True, "reason": "x"},
        {"category": "not a category", "reason": "x"},
        {"sourced": True, "reason": "x" * 501},
        {"sourced": True, "reason": "x", "extra": 1},
    ):
        assert (await docs_client.patch(txn_url, json=body, headers=headers())).status_code == 422
    for body in (
        {"counts_toward_dti": False},
        {"counts_toward_dti": False, "reason": ""},
        {"reason": "x"},
    ):
        assert (await docs_client.patch(debt_url, json=body, headers=headers())).status_code == 422
    changes = "SELECT id FROM audit_events WHERE action ~ 'reclassified|sourced|included|excluded'"
    assert await rows(session, changes) == []


async def test_only_a_deposit_can_be_sourced_and_a_category_must_change(
    docs_client: httpx.AsyncClient,
    session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    analysis = await daniel(docs_client, session, session_factory)
    rent = line(analysis, "OAKMONT APARTMENTS RENT")

    sourced = await docs_client.patch(
        f"{BASE}/latest/transactions/{rent['id']}",
        json={"sourced": True, "reason": "x"},
        headers=headers(),
    )
    same = await docs_client.patch(
        f"{BASE}/latest/transactions/{rent['id']}",
        json={"category": "housing payment", "reason": "x"},
        headers=headers(),
    )

    assert (sourced.status_code, sourced.json()["code"]) == (422, "not_a_deposit")
    assert (same.status_code, same.json()["code"]) == (422, "no_change")


async def test_a_line_or_debt_that_is_not_there_is_a_404(
    docs_client: httpx.AsyncClient,
    session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await daniel(docs_client, session, session_factory)
    unknown = uuid.uuid4()

    for url, body in (
        (f"{BASE}/latest/transactions/{unknown}", {"sourced": True, "reason": "x"}),
        (f"{BASE}/latest/transactions/nope", {"sourced": True, "reason": "x"}),
        (f"{BASE}/latest/obligations/{unknown}", {"counts_toward_dti": True, "reason": "x"}),
        (f"{BASE}/latest/obligations/nope", {"counts_toward_dti": True, "reason": "x"}),
    ):
        assert (await docs_client.patch(url, json=body, headers=headers())).status_code == 404


async def test_a_change_waits_for_the_run_in_progress(
    docs_client: httpx.AsyncClient,
    session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    analysis = await daniel(docs_client, session, session_factory)
    zelle = line(analysis, "ZELLE FROM PATRICIA OWENS REF 8841")["id"]
    await start(docs_client)  # queued, not run: it is now the newest

    response = await docs_client.patch(
        f"{BASE}/latest/transactions/{zelle}",
        json={"sourced": True, "reason": "x"},
        headers=headers(),
    )

    assert (response.status_code, response.json()["code"]) == (409, "analysis_not_ready")


async def test_a_line_of_another_case_is_not_found_here(
    docs_client: httpx.AsyncClient,
    session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await daniel(docs_client, session, session_factory)
    other = await seed_document(session, ANGELA, "bank_statement", {"account_last4": "1111"})
    foreign = (
        await session.execute(
            sa.text(
                "INSERT INTO transactions (document_id, line_ref, posted_on, description, amount, "
                "direction, category) "
                "VALUES (:d, 'p1-L1', '2026-07-01', 'X', 5, 'credit', 'refund') "
                "RETURNING id"
            ),
            {"d": other},
        )
    ).scalar_one()

    response = await docs_client.patch(
        f"{BASE}/latest/transactions/{foreign}",
        json={"sourced": True, "reason": "x"},
        headers=headers(),
    )

    assert response.status_code == 404


# --- failure, queue, access ------------------------------------------------------------------


async def test_a_failure_fails_the_job_and_leaks_no_document_text(
    docs_client: httpx.AsyncClient,
    session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
    caplog: pytest.LogCaptureFixture,
) -> None:
    await seed_all(session)

    class Broken:
        async def label(self, *_: Any, **__: Any) -> Any:
            raise RuntimeError("OAKMONT APARTMENTS RENT 1,425.00 Daniel Reyes")

    response = await start(docs_client)
    await work(response.json(), session_factory, labeller=Broken())

    job = (await rows(session, "SELECT status, error FROM jobs"))[0]
    assert (job.status, job.error) == (
        "failed",
        "The asset and liability analysis could not be completed.",
    )
    assert (await rows(session, "SELECT status FROM analysis_runs"))[0].status == "failed"
    assert "OAKMONT" not in caplog.text and "Daniel" not in caplog.text
    assert "RuntimeError" in caplog.text


async def test_a_queue_that_is_down_is_a_503_and_the_run_is_marked_failed(
    docs_client: httpx.AsyncClient, session: AsyncSession, fake_queue: FakeQueue
) -> None:
    fake_queue.fail = True

    response = await start(docs_client)

    assert response.status_code == 503 and response.json()["code"] == "queue_unavailable"
    assert (await rows(session, "SELECT status FROM analysis_runs"))[0].status == "failed"


async def test_no_analysis_yet_is_a_404(docs_client: httpx.AsyncClient) -> None:
    response = await docs_client.get(f"{BASE}/latest", headers=headers())

    assert response.status_code == 404 and response.json()["code"] == "not_found"


async def test_a_case_the_caller_cannot_see_is_a_404_on_every_endpoint(
    docs_client: httpx.AsyncClient,
    session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    analysis = await daniel(docs_client, session, session_factory)
    lm = headers(Role.LM_SPECIALIST)  # Daniel's case is a Pillar 1 case
    zelle = line(analysis, "ZELLE FROM PATRICIA OWENS REF 8841")["id"]
    harbor = debt(analysis, "Harbor Retail Card")["id"]

    assert (await docs_client.post(BASE, headers=lm)).status_code == 404
    assert (await docs_client.get(f"{BASE}/latest", headers=lm)).status_code == 404
    sourced = {"sourced": True, "reason": "x"}
    assert (
        await docs_client.patch(f"{BASE}/latest/transactions/{zelle}", json=sourced, headers=lm)
    ).status_code == 404
    counted = {"counts_toward_dti": False, "reason": "x"}
    assert (
        await docs_client.patch(f"{BASE}/latest/obligations/{harbor}", json=counted, headers=lm)
    ).status_code == 404
    assert value(await latest(docs_client), "monthly_obligations") == "693.00"


async def test_the_admin_sees_both_pillars_and_no_token_is_a_401(
    docs_client: httpx.AsyncClient,
    session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await daniel(docs_client, session, session_factory)

    assert (await docs_client.get(f"{BASE}/latest", headers=headers(Role.ADMIN))).status_code == 200
    assert (await docs_client.get(f"{BASE}/latest")).status_code == 401
    assert (await docs_client.post(BASE)).status_code == 401
    assert (
        await docs_client.patch(f"{BASE}/latest/obligations/{uuid.uuid4()}", json={})
    ).status_code == 401
    assert (await docs_client.put(SCENARIO_URL, json=SCENARIO_BODY)).status_code == 401


async def test_a_malformed_case_id_is_a_404(docs_client: httpx.AsyncClient) -> None:
    for method, path in (
        ("get", "/api/v1/cases/nope/asset-liability/latest"),
        ("post", "/api/v1/cases/nope/asset-liability"),
        ("get", "/api/v1/cases/nope/loan-scenario"),
    ):
        response = await docs_client.request(method, path, headers=headers())
        assert response.status_code == 404


async def test_no_text_in_the_response_says_approve_deny_offer_eligible_or_qualifies(
    docs_client: httpx.AsyncClient,
    session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    analysis = await daniel(docs_client, session, session_factory)

    texts = re.findall(r'"([^"]+)"', json.dumps(analysis))
    assert texts and not [t for t in texts if BLOCKED.search(t)]


# --- what if (for the Researcher) --------------------------------------------------------------


async def test_a_what_if_on_the_stored_run_changes_nothing_stored(
    docs_client: httpx.AsyncClient,
    session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await daniel(docs_client, session, session_factory)

    result = await asset_runs.what_if(
        session,
        DANIEL,
        WhatIfChanges(drop_obligations=("Harbor Retail Card",), loan_amount=D("320000.00")),
    )

    assert result is not None
    assert result.calc("dti").working == "(1,980.00 + 658.00) / 5,980.00 = 44.11%"
    assert result.calc("ltv").working == "320,000.00 / 400,000.00 = 80.00%"
    assert result.unmatched == []
    assert value(await latest(docs_client), "monthly_obligations") == "693.00"  # nothing stored


async def test_a_what_if_with_no_finished_analysis_is_none(session: AsyncSession) -> None:
    assert await asset_runs.what_if(session, DANIEL, WhatIfChanges()) is None

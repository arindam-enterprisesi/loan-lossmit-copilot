"""Hardship reading, confirmations and the budget through the API, the worker and Postgres (FD 7).

Angela Whitfield's documents are stored as the real reader leaves them (an active extraction run
with fields; the statement lines labelled by the keyword ``FakeLabeller``) and the letter is read by
a stub reader that returns Arindam's worked example, so no model is called. The budget must give the
Feature Design's figures to the cent, a confirmation or an adjustment must recalculate at once and
keep what the system produced beside the change, and every change must be audited. Only the loss
mitigation specialist confirms and adjusts; the administrator makes no case decisions.
"""

from __future__ import annotations

import json
import re
import uuid
from collections.abc import Sequence
from datetime import date
from pathlib import Path
from typing import Any

import httpx
import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.demo.hardship import load_seed_profile, seed_hardship_profile
from app.db.enums import Role
from app.db.models import AnalysisRun
from app.db.seed import case_id, seed
from app.llm.checks import verify_quotes
from app.llm.tasks import DocumentLine
from app.prompts.schemas.hardship import load_hardship_config
from app.services import budget_runs, hardship, hardship_runs
from app.services.transaction_labels import FakeLabeller
from app.worker import run_hardship_reading
from tests.db.conftest import FakeQueue, auth_headers
from tests.db.test_hardship_api import add_letter
from tests.db.test_income_api import seed_document

ANGELA = case_id("Angela Whitfield — hardship")
DANIEL = case_id("Daniel Reyes — purchase")
BASE = f"/api/v1/cases/{ANGELA}/hardship-assessment"
DATA = json.loads(
    (
        Path(__file__).resolve().parents[3] / "data/synthetic/scenarios/angela_whitfield.json"
    ).read_text(encoding="utf-8")
)
BUDGET = DATA["expected"]["budget"]
CONFIG = load_hardship_config()
BLOCKED = re.compile(r"\b(approve[sd]?|deny|denied|offer(s|ed)?|eligible|qualifies)\b", re.I)


@pytest.fixture(autouse=True)
async def seeded(session: AsyncSession) -> None:
    await seed(session, "demo-pass")


def headers(role: Role = Role.LM_SPECIALIST) -> dict[str, str]:
    return auth_headers(role)


# --- Angela's documents ----------------------------------------------------------------------


def doc(doc_type: str) -> list[dict[str, Any]]:
    return [d for d in DATA["documents"] if d["type"] == doc_type]


async def seed_documents(session: AsyncSession, *, application: bool = True) -> uuid.UUID:
    """The letter (with its lines), the stubs, the statements, the mortgage statement and the
    application, as the reader leaves them."""
    letter = await add_letter(session, ANGELA)
    for minutes, stub in enumerate(doc("pay_stub")):
        f = stub["facts"]
        await seed_document(
            session,
            ANGELA,
            "pay_stub",
            {
                "employer_name": f["employer"]["name"],
                "employee_name": f["employee"],
                "pay_frequency": f["pay_frequency"],
                "pay_period_start": f["period_start"],
                "pay_period_end": f["period_end"],
                "pay_date": f["pay_date"],
                "gross_pay_current": f["gross_current"],
                "net_pay_current": f["net_current"],
            },
            minutes=minutes,
            lines={
                "gross_pay_current": f"p1-L{14 + minutes}",
                "net_pay_current": f"p1-L{24 + minutes}",
            },
        )
    for minutes, statement in enumerate(doc("bank_statement")):
        f = statement["facts"]
        values = {
            "institution_name": f["bank"],
            "account_holder": "Angela Whitfield",
            "account_last4": f["account_last4"],
            "statement_period_start": f["period_start"],
            "statement_period_end": f["period_end"],
            "opening_balance": f["opening_balance"],
            "closing_balance": f["closing_balance"],
        }
        lines = {"closing_balance": "p3-L12"}
        for n, t in enumerate(f["transactions"], start=1):
            for part in ("date", "description", "amount"):
                values[f"txn_{n:03d}_{part}"] = t[part]
                lines[f"txn_{n:03d}_{part}"] = f"p1-L{14 + n}"
        await seed_document(
            session,
            ANGELA,
            "bank_statement",
            values,
            minutes=10 + minutes,
            lines=lines,
            period=(date.fromisoformat(f["period_start"]), date.fromisoformat(f["period_end"])),
        )
    m = doc("mortgage_statement")[0]["facts"]
    await seed_document(
        session,
        ANGELA,
        "mortgage_statement",
        {
            "servicer": m["servicer"],
            "borrower_names": m["borrower"],
            "loan_number": m["loan_number"],
            "unpaid_principal_balance": m["unpaid_principal_balance"],
            "regular_monthly_payment": m["monthly_payment"],
            "past_due_amount": m["past_due_amount"],
            "total_amount_due": m["total_due"],
        },
        minutes=20,
        lines={"regular_monthly_payment": "p1-L12", "past_due_amount": "p1-L14"},
    )
    if application:
        a = doc("mortgage_assistance_application")[0]["facts"]
        values = {
            "borrower_names": a["borrower"],
            "loan_number": a["loan_number"],
            "intent": a["intent"],
            "total_monthly_expenses": a["total_expenses"],
        }
        lines = {}
        for n, e in enumerate(a["expenses"], start=1):
            values[f"monthly_expenses_{n:03d}_description"] = e["category"]
            values[f"monthly_expenses_{n:03d}_amount"] = e["amount"]
            lines[f"monthly_expenses_{n:03d}_description"] = f"p1-L{20 + n}"
            lines[f"monthly_expenses_{n:03d}_amount"] = f"p1-L{20 + n}"
        values["monthly_income_001_description"] = "Gross monthly income"
        values["monthly_income_001_amount"] = a["monthly_gross_income"]
        for n, r in enumerate((r for r in a["hardship_reasons"] if r["checked"]), start=1):
            values[f"hardship_reasons_{n:03d}_reason"] = r["reason"]
        await seed_document(
            session, ANGELA, "mortgage_assistance_application", values, minutes=21, lines=lines
        )
    return letter


class StubReader:
    """Arindam's worked example for any letter, with its quotes checked against the lines."""

    def __init__(self) -> None:
        self.calls = 0

    async def read(
        self, lines: Sequence[DocumentLine], *, application_reasons: Sequence[str]
    ) -> hardship.HardshipReading:
        self.calls += 1
        profile = load_seed_profile(CONFIG)
        checks = verify_quotes(profile, lines, max_quote_chars=CONFIG.max_quote_chars)
        return hardship.HardshipReading(profile, checks, "stub", "stub-model")


class BrokenReader:
    async def read(self, *_: Any, **__: Any) -> Any:
        raise RuntimeError("cut my hours from 40 to 30 a week Angela Whitfield")


class BrokenLabeller:
    async def label(self, *_: Any, **__: Any) -> Any:
        raise RuntimeError("PINEBROOK MORTGAGE SERVICING 1,720.00")


async def start(client: httpx.AsyncClient, role: Role = Role.LM_SPECIALIST) -> httpx.Response:
    return await client.post(BASE, headers=headers(role))


async def work(
    accepted: dict[str, Any], factory: async_sessionmaker[AsyncSession], **ctx: Any
) -> None:
    context = {
        "session_factory": factory,
        "hardship_reader": StubReader(),
        "labeller": FakeLabeller(),
        **ctx,
    }
    await run_hardship_reading(context, accepted["job"]["id"], str(_user_id()))


def _user_id() -> uuid.UUID:
    from app.db.seed import user_id

    return user_id("lm_specialist")


async def read_letter(
    client: httpx.AsyncClient, factory: async_sessionmaker[AsyncSession], **ctx: Any
) -> dict[str, Any]:
    response = await start(client)
    assert response.status_code == 202, response.text
    accepted: dict[str, Any] = response.json()
    await work(accepted, factory, **ctx)
    return accepted


async def latest(client: httpx.AsyncClient, role: Role = Role.LM_SPECIALIST) -> dict[str, Any]:
    response = await client.get(f"{BASE}/latest", headers=headers(role))
    assert response.status_code == 200, response.text
    return response.json()  # type: ignore[no-any-return]


async def ready(
    client: httpx.AsyncClient, session: AsyncSession, factory: async_sessionmaker[AsyncSession]
) -> dict[str, Any]:
    """Documents stored, the letter read, the budget built: what the specialist sees."""
    await seed_documents(session)
    await read_letter(client, factory)
    return await latest(client)


def measure(body: dict[str, Any], name: str) -> dict[str, Any]:
    return next(m for m in body["measures"] if m["name"] == name)


def row(body: dict[str, Any], category: str) -> dict[str, Any]:
    return next(b for b in body["budget"] if b["category"] == category)


async def rows(session: AsyncSession, sql: str, **params: Any) -> list[Any]:
    return list((await session.execute(sa.text(sql), params)).all())


# --- reading the letter ----------------------------------------------------------------------


async def test_reading_queues_a_job_and_the_worker_stores_a_model_reading_beside_the_sample(
    docs_client: httpx.AsyncClient,
    session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
    fake_queue: FakeQueue,
) -> None:
    await seed_documents(session)
    await seed_hardship_profile(session, ANGELA)

    response = await start(docs_client)

    assert response.status_code == 202
    accepted = response.json()
    assert accepted["job"]["kind"] == "hardship_reading" and accepted["job"]["status"] == "queued"
    assert fake_queue.calls == [
        (
            "run_hardship_reading",
            (accepted["job"]["id"], str(_user_id())),
            accepted["job"]["id"],
        )
    ]
    reader = StubReader()
    await work(accepted, session_factory, hardship_reader=reader)
    job = (await rows(session, "SELECT status, stage, progress, error FROM jobs"))[0]
    assert tuple(job) == ("succeeded", "done", 1.0, None)
    assert reader.calls == 1
    body = await latest(docs_client)
    assert body["source"] == "model"  # the newest reading; the seeded sample stays as history
    sources = [
        r.source
        for r in await rows(session, "SELECT source FROM hardship_profiles ORDER BY created_at")
    ]
    assert sources == ["seeded_sample", "model"]
    assert all(
        i["verified"] for i in [body["profile"]["primary_reason"], body["profile"]["intent"]]
    )


async def test_with_no_letter_there_is_nothing_to_read(
    docs_client: httpx.AsyncClient, session: AsyncSession, fake_queue: FakeQueue
) -> None:
    response = await start(docs_client)

    assert (response.status_code, response.json()["code"]) == (409, "no_letter")
    assert fake_queue.calls == [] and await rows(session, "SELECT id FROM jobs") == []


async def test_a_reader_that_fails_fails_the_job_keeps_the_sample_and_leaks_no_text(
    docs_client: httpx.AsyncClient,
    session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
    caplog: pytest.LogCaptureFixture,
) -> None:
    await seed_documents(session)
    await seed_hardship_profile(session, ANGELA)

    await read_letter(docs_client, session_factory, hardship_reader=BrokenReader())

    job = (await rows(session, "SELECT status, error FROM jobs"))[0]
    assert (job.status, job.error) == ("failed", "The hardship letter could not be read.")
    assert (await latest(docs_client))["source"] == "seeded_sample"
    assert "Angela" not in caplog.text and "cut my hours" not in caplog.text
    assert "RuntimeError" in caplog.text


async def test_a_budget_that_fails_keeps_the_reading_and_says_so(
    docs_client: httpx.AsyncClient,
    session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
    caplog: pytest.LogCaptureFixture,
) -> None:
    await seed_documents(session)

    await read_letter(docs_client, session_factory, labeller=BrokenLabeller())

    job = (await rows(session, "SELECT status, error FROM jobs"))[0]
    assert (job.status, job.error) == (
        "failed",
        "The letter was read, but the budget could not be completed.",
    )
    body = await latest(docs_client)
    assert body["source"] == "model" and body["budget"] == []
    assert body["budget_note"] == "The budget has not been computed for this reading yet."
    assert "PINEBROOK" not in caplog.text


async def test_a_queue_that_is_down_is_a_503_and_the_job_is_marked_failed(
    docs_client: httpx.AsyncClient, session: AsyncSession, fake_queue: FakeQueue
) -> None:
    await seed_documents(session)
    fake_queue.fail = True

    response = await start(docs_client)

    assert (response.status_code, response.json()["code"]) == (503, "queue_unavailable")
    assert (await rows(session, "SELECT status FROM jobs"))[0].status == "failed"


# --- the budget, to the cent -----------------------------------------------------------------


async def test_the_budget_has_angelas_figures_to_the_cent(
    docs_client: httpx.AsyncClient,
    session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    body = await ready(docs_client, session, session_factory)

    assert measure(body, "documented_gross_monthly_income")["value"] == "4200.00"
    assert measure(body, "documented_net_monthly_income")["value"] == "3350.00"
    assert measure(body, "income_change")["working"] == "(4,200.00 - 5,600.00) / 5,600.00 = -25.00%"
    assert measure(body, "stated_expenses_total")["value"] == BUDGET["stated_total"] == "3420.00"
    assert (
        measure(body, "observed_expenses_total")["value"] == BUDGET["observed_total"] == "3630.00"
    )
    assert measure(body, "surplus_stated")["working"] == "3,350.00 - 3,420.00 = -70.00"
    assert measure(body, "surplus_observed")["working"] == "3,350.00 - 3,630.00 = -280.00"
    assert measure(body, "housing_ratio")["working"] == "1,720.00 / 4,200.00 = 40.95%"
    assert measure(body, "housing_ratio_before_cut")["working"] == "1,720.00 / 5,600.00 = 30.71%"
    assert measure(body, "arrears")["value"] == "5160.00"
    assert measure(body, "liquid_assets")["value"] == "640.25"
    assert (
        measure(body, "liquid_assets_share_of_arrears")["working"] == "640.25 / 5,160.00 = 12.41%"
    )
    assert body["budget_note"] is None
    assert body["measures"][0]["config_version"].startswith("hardship@")


async def test_each_line_shows_stated_beside_observed_and_only_other_is_flagged(
    docs_client: httpx.AsyncClient,
    session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    body = await ready(docs_client, session, session_factory)

    assert [b["category"] for b in body["budget"]] == [
        "Housing (mortgage)",
        "Utilities",
        "Food and everyday",
        "Loan payments",
        "Other",
    ]
    for category, stated in BUDGET["stated"].items():
        assert row(body, category)["stated"] == stated
        assert row(body, category)["observed"] == BUDGET["observed"][category]
    housing = row(body, "Housing (mortgage)")
    assert (housing["observed_month"], housing["observed_calc"]["working"]) == (
        "2026-07",
        "July 2026: 1,720.00",
    )
    assert row(body, "Utilities")["observed_month"] == "2026-09"
    assert [b["category"] for b in body["budget"] if b["flagged"]] == ["Other"]
    other = row(body, "Other")
    assert (other["stated"], other["observed"], other["difference"]) == (
        "200.00",
        "410.00",
        "210.00",
    )
    assert [f["code"] for f in body["budget_flags"]] == ["HB-W101"]
    assert body["budget_flags"][0]["message"] == (
        "Other: 200.00 stated against 410.00 in the statements, a difference of 210.00."
    )
    # Every figure points at the document lines it came from (rule 2).
    assert housing["observed_calc"]["evidence"][0]["field"] == "transaction"
    assert housing["stated_calc"]["evidence"][0]["field"] == "monthly_expenses"
    assert measure(body, "arrears")["evidence"][0]["field"] == "past_due_amount"


async def test_the_consistency_checks_show_both_values_and_agree_for_angela(
    docs_client: httpx.AsyncClient,
    session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    body = await ready(docs_client, session, session_factory)

    checks = {c["name"]: c for c in body["checks"]}
    assert set(checks) == {
        "check_income_stated_vs_documented",
        "check_pay_vs_hours",
        "check_reason_vs_letter",
        "check_intent_vs_letter",
    }
    assert all(c["agrees"] for c in checks.values())
    assert "-25.00%" in checks["check_pay_vs_hours"]["working"]
    assert checks["check_pay_vs_hours"]["values"] == {
        "pay_change": "-0.250000",
        "hours_change": "-0.250000",
    }
    assert "check_pay_vs_hours" not in {m["name"] for m in body["measures"]}


async def test_the_statement_lines_were_labelled_for_the_budget_and_kept(
    docs_client: httpx.AsyncClient,
    session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await ready(docs_client, session, session_factory)

    labelled = await rows(
        session, "SELECT count(*), count(*) FILTER (WHERE category_source = 'ai') FROM transactions"
    )
    expected = sum(len(d["facts"]["transactions"]) for d in doc("bank_statement"))
    assert tuple(labelled[0]) == (expected, expected)


async def test_without_the_application_the_stated_side_says_what_is_missing(
    docs_client: httpx.AsyncClient,
    session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await seed_documents(session, application=False)
    await read_letter(docs_client, session_factory)

    body = await latest(docs_client)

    assert all(b["stated"] is None and not b["flagged"] for b in body["budget"])
    assert measure(body, "surplus_observed")["value"] == "-280.00"
    assert "surplus_stated" not in {m["name"] for m in body["measures"]}
    info = [f["message"] for f in body["budget_flags"] if f["code"] == "HB-I101"]
    assert "Cannot compute stated expenses: the application's monthly expenses not found." in info


async def test_the_budget_of_a_seeded_profile_with_no_documents_says_it_cannot_compute(
    docs_client: httpx.AsyncClient, session: AsyncSession
) -> None:
    await seed_hardship_profile(session, ANGELA)
    view = await hardship_runs.latest(session, ANGELA)
    assert view is not None

    await budget_runs.compute_for_run(session, view.run)
    body = await latest(docs_client)

    assert body["measures"] == []
    infos = [f["message"] for f in body["budget_flags"]]
    assert len(infos) >= 5 and all(m.startswith("Cannot compute") for m in infos)
    assert all(f["severity"] == "info" for f in body["budget_flags"])
    assert all(b["stated"] is None and b["observed"] is None for b in body["budget"])


# --- confirming the reading ------------------------------------------------------------------


def confirm_url() -> str:
    return f"{BASE}/latest/confirmations"


async def test_confirming_an_item_as_read_adds_a_labelled_confirmation_and_changes_nothing_else(
    docs_client: httpx.AsyncClient,
    session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    before = await ready(docs_client, session, session_factory)

    response = await docs_client.put(confirm_url(), json={"intent": {}}, headers=headers())

    assert response.status_code == 200, response.text
    body = response.json()
    intent = body["profile"]["intent"]
    assert intent["category"] == "keep"  # the reading is untouched (rule 6)
    confirmation = intent["confirmation"]
    assert (confirmation["status"], confirmation["value"], confirmation["original"]) == (
        "confirmed",
        "keep",
        "keep",
    )
    assert confirmation["label"] == "reviewer-confirmed" and confirmation["by"] == str(_user_id())
    assert (
        body["profile"]["duration"]["confirmation"] is None
    )  # an item nobody named is unconfirmed
    assert body["confirmed_by"] == str(_user_id()) and body["confirmed_at"]
    assert body["measures"] == before["measures"]  # same figures, same ids, same order
    event = (
        await rows(
            session,
            "SELECT before, after, reason FROM audit_events WHERE action = 'hardship.confirmed'",
        )
    )[0]
    assert event.after["intent"]["status"] == "confirmed" and event.reason is None


async def test_correcting_the_duration_keeps_what_the_letter_said_and_records_who_and_why(
    docs_client: httpx.AsyncClient,
    session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await ready(docs_client, session, session_factory)

    response = await docs_client.put(
        confirm_url(),
        json={
            "duration": {
                "value": "temporary",
                "reason": "Her manager confirmed hours return in March.",
            }
        },
        headers=headers(),
    )

    duration = response.json()["profile"]["duration"]
    assert duration["category"] == "unknown"  # as read from the letter
    assert duration["confirmation"]["value"] == "temporary"
    assert (duration["confirmation"]["status"], duration["confirmation"]["original"]) == (
        "corrected",
        "unknown",
    )
    assert duration["confirmation"]["reason"].startswith("Her manager")
    stored = (await rows(session, "SELECT duration FROM hardship_profiles WHERE source = 'model'"))[
        0
    ].duration
    assert stored["category"] == "unknown" and stored["confirmation"]["value"] == "temporary"
    event = (
        await rows(
            session,
            "SELECT before, after, reason FROM audit_events WHERE action = 'hardship.confirmed'",
        )
    )[0]
    assert event.before["duration"] == "unknown" and event.after["duration"]["value"] == "temporary"
    assert event.reason.startswith("duration: Her manager")


async def test_confirming_again_replaces_the_confirmation_and_the_audit_trail_keeps_the_first(
    docs_client: httpx.AsyncClient,
    session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await ready(docs_client, session, session_factory)
    await docs_client.put(
        confirm_url(),
        json={"duration": {"value": "temporary", "reason": "first"}},
        headers=headers(),
    )

    response = await docs_client.put(
        confirm_url(),
        json={"duration": {"value": "long_term", "reason": "second"}},
        headers=headers(),
    )

    assert response.json()["profile"]["duration"]["confirmation"]["value"] == "long_term"
    events = await rows(
        session,
        "SELECT before, after FROM audit_events WHERE action = 'hardship.confirmed' ORDER BY id",
    )
    assert [e.after["duration"]["value"] for e in events] == ["temporary", "long_term"]
    assert events[1].before["duration"] == "temporary"


async def test_a_confirmed_reason_that_differs_from_the_application_is_flagged_at_once(
    docs_client: httpx.AsyncClient,
    session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    before = await ready(docs_client, session, session_factory)
    assert "HB-W103" not in [f["code"] for f in before["budget_flags"]]

    response = await docs_client.put(
        confirm_url(),
        json={"primary_reason": {"value": "unemployment", "reason": "She was let go in October."}},
        headers=headers(),
    )

    flags = {f["code"]: f for f in response.json()["budget_flags"]}
    assert flags["HB-W103"]["message"] == (
        'The application ticks "Reduction in income" '
        'but the letter\'s main reason is "unemployment".'
    )
    check = next(c for c in response.json()["checks"] if c["name"] == "check_reason_vs_letter")
    assert check["agrees"] is False


async def test_a_confirmation_needs_a_real_value_a_reason_for_a_correction_and_something_to_confirm(
    docs_client: httpx.AsyncClient,
    session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await ready(docs_client, session, session_factory)

    for body, status, code in (
        ({}, 422, "nothing_to_confirm"),
        ({"duration": {"value": "temporary"}}, 422, "reason_required"),
        ({"duration": {"value": "temporary", "reason": "  "}}, 422, "reason_required"),
        ({"duration": {"value": "forever", "reason": "x"}}, 422, "invalid_value"),
        ({"intent": {"value": "approved", "reason": "x"}}, 422, "invalid_value"),
        ({"primary_reason": {"value": "not_a_category", "reason": "x"}}, 422, "invalid_value"),
        ({"onset": {"value": "July 2026", "reason": "x"}}, 422, "invalid_value"),
        ({"onset": {"value": "2026-13", "reason": "x"}}, 422, "invalid_value"),
    ):
        response = await docs_client.put(confirm_url(), json=body, headers=headers())
        assert (response.status_code, response.json()["code"]) == (status, code), body
    for bad in ({"duration": {"reason": "x" * 501}}, {"duration": {"extra": 1}}, {"surprise": {}}):
        assert (
            await docs_client.put(confirm_url(), json=bad, headers=headers())
        ).status_code == 422
    assert (
        await rows(session, "SELECT id FROM audit_events WHERE action = 'hardship.confirmed'") == []
    )
    assert (await latest(docs_client))["confirmed_by"] is None


async def test_the_onset_is_confirmed_as_a_month(
    docs_client: httpx.AsyncClient,
    session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await ready(docs_client, session, session_factory)

    as_read = await docs_client.put(confirm_url(), json={"onset": {}}, headers=headers())
    fixed = await docs_client.put(
        confirm_url(),
        json={"onset": {"value": "2026-06", "reason": "Hours were cut in June."}},
        headers=headers(),
    )

    assert as_read.json()["profile"]["onset"]["confirmation"]["value"] == "2026-07"
    assert fixed.json()["profile"]["onset"]["confirmation"]["status"] == "corrected"


async def test_the_rules_see_a_value_only_once_it_is_confirmed(
    docs_client: httpx.AsyncClient,
    session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await ready(docs_client, session, session_factory)
    view = await hardship_runs.latest(session, ANGELA)
    assert view is not None
    assert hardship.effective_values(view.profile)["duration"] == ("unknown", False)

    await docs_client.put(confirm_url(), json={"duration": {}, "intent": {}}, headers=headers())

    view = await hardship_runs.latest(session, ANGELA)
    assert view is not None
    values = hardship.effective_values(view.profile)
    assert values["duration"] == ("unknown", True) and values["intent"] == ("keep", True)
    assert values["onset"][1] is False and values["primary_reason"][1] is False


async def test_the_seeded_sample_can_be_confirmed_too(
    docs_client: httpx.AsyncClient, session: AsyncSession
) -> None:
    await seed_hardship_profile(session, ANGELA)

    response = await docs_client.put(confirm_url(), json={"intent": {}}, headers=headers())

    assert response.status_code == 200
    assert response.json()["source"] == "seeded_sample"
    assert response.json()["profile"]["intent"]["confirmation"]["label"] == "reviewer-confirmed"


# --- adjusting the budget --------------------------------------------------------------------


def adjust_url(line: str) -> str:
    return f"{BASE}/latest/budget/{line}"


async def test_marking_a_spend_as_one_off_updates_the_measures_at_once_and_keeps_the_original(
    docs_client: httpx.AsyncClient,
    session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    body = await ready(docs_client, session, session_factory)
    other = row(body, "Other")

    response = await docs_client.patch(
        adjust_url(other["id"]),
        json={"adjusted_amount": "200.00", "reason": "The 410.00 included a one-off family gift."},
        headers=headers(),
    )

    assert response.status_code == 200, response.text
    after = response.json()
    adjusted = row(after, "Other")
    assert (adjusted["observed"], adjusted["adjusted"], adjusted["effective_observed"]) == (
        "410.00",
        "200.00",
        "200.00",
    )
    assert adjusted["adjustment_reason"].startswith("The 410.00") and adjusted["flagged"] is False
    assert adjusted["change"]["by"] == str(_user_id()) and adjusted["change"]["reason"].startswith(
        "The 410.00"
    )
    assert measure(after, "observed_expenses_total")["value"] == "3420.00"
    assert measure(after, "surplus_observed")["value"] == "-70.00"
    assert after["budget_flags"] == []
    assert adjusted["id"] == other["id"]  # the line keeps its id through the recalculation
    stored = (
        await rows(
            session,
            "SELECT observed_amount, adjusted_amount FROM budget_lines WHERE id = :i",
            i=other["id"],
        )
    )[0]
    assert (stored.observed_amount, stored.adjusted_amount) == (410, 200)
    event = (
        await rows(
            session,
            "SELECT before, after, reason FROM audit_events WHERE action = 'budget.line_adjusted'",
        )
    )[0]
    assert (
        event.before["surplus_observed"] == "-280.00"
        and event.after["surplus_observed"] == "-70.00"
    )
    assert event.before["adjusted_amount"] is None and event.after["adjusted_amount"] == "200.00"
    assert event.reason.startswith("The 410.00")


async def test_clearing_an_adjustment_brings_the_statements_amount_back(
    docs_client: httpx.AsyncClient,
    session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    body = await ready(docs_client, session, session_factory)
    other = row(body, "Other")["id"]
    await docs_client.patch(
        adjust_url(other),
        json={"adjusted_amount": "200.00", "reason": "one-off"},
        headers=headers(),
    )

    response = await docs_client.patch(
        adjust_url(other),
        json={"adjusted_amount": None, "reason": "The gift was not one-off after all."},
        headers=headers(),
    )

    after = response.json()
    cleared = row(after, "Other")
    assert (cleared["adjusted"], cleared["effective_observed"], cleared["change"]) == (
        None,
        "410.00",
        None,
    )
    assert cleared["flagged"] is True
    assert measure(after, "surplus_observed")["value"] == "-280.00"
    events = await rows(
        session, "SELECT action, reason FROM audit_events WHERE action LIKE 'budget.%' ORDER BY id"
    )
    assert [e.action for e in events] == ["budget.line_adjusted", "budget.adjustment_cleared"]
    assert events[1].reason == "The gift was not one-off after all."


async def test_a_new_reading_carries_an_adjustment_to_its_own_budget(
    docs_client: httpx.AsyncClient,
    session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    body = await ready(docs_client, session, session_factory)
    await docs_client.patch(
        adjust_url(row(body, "Other")["id"]),
        json={"adjusted_amount": "200.00", "reason": "one-off gift"},
        headers=headers(),
    )

    await read_letter(docs_client, session_factory)

    again = await latest(docs_client)
    assert again["run_id"] != body["run_id"]
    other = row(again, "Other")
    assert (other["observed"], other["adjusted"], other["adjustment_reason"]) == (
        "410.00",
        "200.00",
        "one-off gift",
    )
    assert other["change"]["by"] == str(_user_id())
    assert measure(again, "surplus_observed")["value"] == "-70.00"


async def test_an_adjustment_needs_a_reason_a_sensible_amount_and_a_line_that_is_there(
    docs_client: httpx.AsyncClient,
    session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    body = await ready(docs_client, session, session_factory)
    line = row(body, "Other")["id"]

    for payload in (
        {"adjusted_amount": "200.00"},
        {"adjusted_amount": "200.00", "reason": "   "},
        {"adjusted_amount": "-1.00", "reason": "x"},
        {"adjusted_amount": "1.234", "reason": "x"},
        {"adjusted_amount": "abc", "reason": "x"},
        {"adjusted_amount": "200.00", "reason": "x" * 501},
        {"adjusted_amount": "200.00", "reason": "x", "extra": 1},
    ):
        assert (
            await docs_client.patch(adjust_url(line), json=payload, headers=headers())
        ).status_code == 422, payload
    for missing in (str(uuid.uuid4()), "nope"):
        response = await docs_client.patch(
            adjust_url(missing), json={"adjusted_amount": "1.00", "reason": "x"}, headers=headers()
        )
        assert response.status_code == 404
    assert await rows(session, "SELECT id FROM audit_events WHERE action LIKE 'budget.%'") == []
    assert row(await latest(docs_client), "Other")["adjusted"] is None


async def test_a_line_with_no_statements_cannot_be_adjusted_against_them(
    docs_client: httpx.AsyncClient, session: AsyncSession
) -> None:
    await seed_hardship_profile(session, ANGELA)
    view = await hardship_runs.latest(session, ANGELA)
    assert view is not None
    await budget_runs.compute_for_run(session, view.run)
    line = row(await latest(docs_client), "Other")["id"]

    response = await docs_client.patch(
        adjust_url(line), json={"adjusted_amount": "10.00", "reason": "x"}, headers=headers()
    )

    assert (response.status_code, response.json()["code"]) == (422, "no_observed_amount")


# --- who may act -----------------------------------------------------------------------------


async def test_only_the_specialist_confirms_and_adjusts_and_the_admin_gets_403(
    docs_client: httpx.AsyncClient,
    session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    body = await ready(docs_client, session, session_factory)
    line = row(body, "Other")["id"]

    for role in (Role.ADMIN, Role.UNDERWRITER):
        assert (
            await docs_client.put(confirm_url(), json={"intent": {}}, headers=headers(role))
        ).status_code == 403
        patch = await docs_client.patch(
            adjust_url(line), json={"adjusted_amount": "1.00", "reason": "x"}, headers=headers(role)
        )
        assert patch.status_code == 403
    assert (await latest(docs_client))["confirmed_by"] is None
    assert row(await latest(docs_client), "Other")["adjusted"] is None


async def test_a_case_of_the_other_pillar_is_a_404_and_the_admin_reads_it(
    docs_client: httpx.AsyncClient,
    session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await ready(docs_client, session, session_factory)

    assert (
        await docs_client.get(f"{BASE}/latest", headers=headers(Role.UNDERWRITER))
    ).status_code == 404
    assert (await docs_client.post(BASE, headers=headers(Role.UNDERWRITER))).status_code == 404
    assert (await docs_client.get(f"{BASE}/latest", headers=headers(Role.ADMIN))).status_code == 200
    daniel = f"/api/v1/cases/{DANIEL}/hardship-assessment"
    assert (
        await docs_client.put(
            f"{daniel}/latest/confirmations", json={"intent": {}}, headers=headers()
        )
    ).status_code == 404
    assert (await docs_client.post(daniel, headers=headers())).status_code == 404


async def test_no_token_is_a_401_and_a_malformed_case_is_a_404(
    docs_client: httpx.AsyncClient,
) -> None:
    assert (await docs_client.post(BASE)).status_code == 401
    assert (await docs_client.put(confirm_url(), json={})).status_code == 401
    assert (await docs_client.patch(adjust_url(str(uuid.uuid4())), json={})).status_code == 401
    assert (
        await docs_client.get("/api/v1/cases/nope/hardship-assessment/latest", headers=headers())
    ).status_code == 404
    assert (
        await docs_client.post("/api/v1/cases/nope/hardship-assessment", headers=headers())
    ).status_code == 404


async def test_a_case_with_no_reading_has_nothing_to_confirm_or_adjust(
    docs_client: httpx.AsyncClient,
) -> None:
    assert (
        await docs_client.put(confirm_url(), json={"intent": {}}, headers=headers())
    ).status_code == 404
    patch = await docs_client.patch(
        adjust_url(str(uuid.uuid4())),
        json={"adjusted_amount": "1.00", "reason": "x"},
        headers=headers(),
    )
    assert patch.status_code == 404


async def test_no_text_in_the_assessment_says_approve_deny_offer_eligible_or_qualifies(
    docs_client: httpx.AsyncClient,
    session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await ready(docs_client, session, session_factory)
    await docs_client.put(
        confirm_url(),
        json={"primary_reason": {"value": "unemployment", "reason": "Laid off."}},
        headers=headers(),
    )
    body = await latest(docs_client)

    texts = re.findall(r'"([^"]+)"', json.dumps(body))
    assert texts and not [t for t in texts if BLOCKED.search(t)]


async def test_the_run_the_budget_belongs_to_is_the_newest_hardship_run(
    docs_client: httpx.AsyncClient,
    session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    body = await ready(docs_client, session, session_factory)

    run = await session.get(AnalysisRun, uuid.UUID(body["run_id"]))
    assert run is not None and run.feature.value == "hardship"
    assert {"hardship", "thresholds"} <= set(run.config_versions)
    assert len(await rows(session, "SELECT id FROM budget_lines WHERE run_id = :r", r=run.id)) == 5

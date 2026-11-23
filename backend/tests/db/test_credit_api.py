"""The credit report analysis through the API, the worker and Postgres (Feature Design 4, D7).

Daniel Reyes's sample report is stored as the pipeline leaves it (an active extraction run with
fields numbered ``score_NNN_*``, ``tradeline_NNN_*`` and ``inquiry_NNN_*``). The worker analyses it
in plain code (no model) and ``GET .../latest`` must give the Feature Design's figures: the
representative score 705, Northgate utilization 36.75%, total revolving utilization 28.00%, one
30-day late payment 19 months before the report date, payments of 693.00, the new Harbor Retail
card matched to its inquiry and the Orion Mortgage inquiry with no account.
"""

from __future__ import annotations

import json
import re
import uuid
from pathlib import Path
from typing import Any

import httpx
import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.enums import Role
from app.db.seed import case_id, seed
from app.worker import run_credit_analysis
from tests.db.conftest import FakeQueue, auth_headers
from tests.db.test_income_api import seed_document

DANIEL = case_id("Daniel Reyes — purchase")
ANGELA = case_id("Angela Whitfield — hardship")
BASE = f"/api/v1/cases/{DANIEL}/credit-analysis"
DATA = json.loads(
    (Path(__file__).resolve().parents[3] / "data/synthetic/scenarios/daniel_reyes.json").read_text(
        encoding="utf-8"
    )
)
REPORT = next(d for d in DATA["documents"] if d["type"] == "credit_report")["facts"]
EXPECTED = DATA["expected"]["credit"]
BLOCKED = re.compile(r"\b(approve[sd]?|deny|denied|offer(s|ed)?|eligible|qualifies)\b", re.I)


@pytest.fixture(autouse=True)
async def seeded(session: AsyncSession) -> None:
    await seed(session, "demo-pass")


def headers(role: Role = Role.UNDERWRITER) -> dict[str, str]:
    return auth_headers(role)


def report_fields(**changes: dict[str, str]) -> tuple[dict[str, str], dict[str, str]]:
    """The report as the reader leaves it: values by field name, and the line each came from."""
    values: dict[str, str] = {
        "consumer_name": REPORT["consumer"],
        "report_date": REPORT["report_date"],
    }
    lines: dict[str, str] = {"report_date": "p1-L2"}
    for n, s in enumerate(REPORT["scores"], start=1):
        values[f"score_{n:03d}_bureau"] = s["bureau"]
        values[f"score_{n:03d}_value"] = str(s["score"])
        lines[f"score_{n:03d}_bureau"] = lines[f"score_{n:03d}_value"] = f"p1-L{4 + n}"
    parts = (
        ("creditor", "creditor"),
        ("account_type", "account_type"),
        ("ownership", "ownership"),
        ("open_date", "open_date"),
        ("status", "status"),
        ("balance", "balance"),
        ("credit_limit", "credit_limit"),
        ("monthly_payment", "monthly_payment"),
        ("past_due", "past_due"),
        ("late_30", "late_30"),
        ("late_60", "late_60"),
        ("late_90", "late_90"),
        ("most_recent_late", "most_recent_late"),
        ("remarks", "remarks"),
    )
    for n, t in enumerate(REPORT["tradelines"], start=1):
        for part, key in parts:
            raw = t[key]
            if raw in (None, ""):
                continue
            values[f"tradeline_{n:03d}_{part}"] = str(raw)
            lines[f"tradeline_{n:03d}_{part}"] = f"p2-L{10 + n}"
    for n, q in enumerate(REPORT["inquiries"], start=1):
        values[f"inquiry_{n:03d}_creditor"] = q["creditor"]
        values[f"inquiry_{n:03d}_date"] = q["date"]
        lines[f"inquiry_{n:03d}_creditor"] = lines[f"inquiry_{n:03d}_date"] = f"p3-L{4 + n}"
    for extra in changes.values():
        values.update(extra)
        lines.update({k: "p1-L3" for k in extra})
    return values, lines


async def seed_report(session: AsyncSession, **changes: dict[str, str]) -> uuid.UUID:
    values, lines = report_fields(**changes)
    return await seed_document(session, DANIEL, "credit_report", values, minutes=20, lines=lines)


async def start(client: httpx.AsyncClient, role: Role = Role.UNDERWRITER) -> httpx.Response:
    return await client.post(BASE, headers=headers(role))


async def analyse(
    client: httpx.AsyncClient, factory: async_sessionmaker[AsyncSession]
) -> dict[str, Any]:
    response = await start(client)
    assert response.status_code == 202, response.text
    accepted = response.json()
    await run_credit_analysis(
        {"session_factory": factory}, accepted["job"]["id"], accepted["analysis_id"]
    )
    return await latest(client)


async def latest(client: httpx.AsyncClient, role: Role = Role.UNDERWRITER) -> dict[str, Any]:
    response = await client.get(f"{BASE}/latest", headers=headers(role))
    assert response.status_code == 200, response.text
    return response.json()  # type: ignore[no-any-return]


def tradeline(body: dict[str, Any], creditor: str) -> dict[str, Any]:
    return next(t for t in body["tradelines"] if t["creditor"] == creditor)


def inquiry(body: dict[str, Any], creditor: str) -> dict[str, Any]:
    return next(i for i in body["inquiries"] if i["creditor"] == creditor)


async def rows(session: AsyncSession, sql: str, **params: Any) -> list[Any]:
    return list((await session.execute(sa.text(sql), params)).all())


# --- running it ------------------------------------------------------------------------------


async def test_starting_queues_a_job_and_a_queued_run(
    docs_client: httpx.AsyncClient, session: AsyncSession, fake_queue: FakeQueue
) -> None:
    await seed_report(session)

    response = await start(docs_client)

    assert response.status_code == 202
    accepted = response.json()
    assert accepted["job"]["kind"] == "credit_analysis" and accepted["job"]["status"] == "queued"
    assert fake_queue.calls == [
        (
            "run_credit_analysis",
            (accepted["job"]["id"], accepted["analysis_id"]),
            accepted["job"]["id"],
        )
    ]
    assert (await latest(docs_client))["status"] == "queued"


async def test_the_worker_stores_the_scores_and_the_representative_score(
    docs_client: httpx.AsyncClient,
    session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await seed_report(session)

    body = await analyse(docs_client, session_factory)

    assert body["status"] == "succeeded" and body["tag"].startswith("Sample credit report")
    assert [(s["bureau"], s["score"]) for s in body["scores"]] == [
        ("Bureau A", 712),
        ("Bureau B", 698),
        ("Bureau C", 705),
    ]
    representative = body["representative"]
    assert representative["score"] == EXPECTED["representative_score"] == 705
    assert representative["bureau"] == "Bureau C"
    assert representative["method"] == "middle_of_three_lower_of_two"
    assert representative["calculation"]["working"] == (
        "Scores 712, 698, 705: the middle of the scores is 705"
    )
    assert [s["is_representative"] for s in body["scores"]] == [False, False, True]


async def test_utilization_is_per_account_and_in_total_with_working(
    docs_client: httpx.AsyncClient,
    session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await seed_report(session)

    body = await analyse(docs_client, session_factory)

    northgate = tradeline(body, "Northgate Card")
    assert northgate["utilization"]["value"] == "0.367500"
    assert northgate["utilization"]["working"] == "2,940.00 / 8,000.00 = 36.75%"
    assert northgate["utilization_over_review_level"] is True
    assert northgate["utilization"]["evidence"][0]["field"] == "tradeline_001"
    assert tradeline(body, "Cardinal Rewards Visa")["utilization_over_review_level"] is False
    assert tradeline(body, "Lakeshore Auto Finance")["utilization"] is None  # installment
    total = body["total_revolving_utilization"]
    assert (total["value"], total["working"]) == ("0.280000", "4,480.00 / 16,000.00 = 28.00%")


async def test_the_late_payment_the_payments_total_and_the_template_summary(
    docs_client: httpx.AsyncClient,
    session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await seed_report(session)

    body = await analyse(docs_client, session_factory)

    northgate = tradeline(body, "Northgate Card")
    assert (northgate["late_30"], northgate["late_in_lookback"]) == (1, True)
    assert northgate["months_since_last_late"]["value"] == "19"
    totals = {c["name"]: c["value"] for c in body["monthly_payments"]}
    assert totals["monthly_payments_total"] == EXPECTED["monthly_payments_total"] == "693.00"
    assert totals["monthly_payments_revolving"] == "163.00"
    assert totals["monthly_payments_installment"] == "530.00"
    assert body["summary"][0] == (
        "One 30-day late payment on Northgate Card, 19 months before the report date."
    )
    assert "Northgate Card utilization is 36.75%, above the review level." in body["summary"]


async def test_inquiries_show_their_matched_account_or_none(
    docs_client: httpx.AsyncClient,
    session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await seed_report(session)

    body = await analyse(docs_client, session_factory)

    harbor, orion = inquiry(body, "Harbor Retail"), inquiry(body, "Orion Mortgage")
    assert harbor["matched_account"] == "Harbor Retail Card" and harbor["in_window"] is True
    assert orion["matched_account"] is None and orion["matched_tradeline_id"] is None
    assert harbor["line_ids"] == ["p3-L5"]
    assert "The Orion Mortgage inquiry has no matching account." in body["summary"]


async def test_the_flags_link_to_the_report_lines_they_describe(
    docs_client: httpx.AsyncClient,
    session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await seed_report(session)

    body = await analyse(docs_client, session_factory)

    assert sorted(f["code"] for f in body["flags"]) == ["CR-I102", "CR-W101", "CR-W102", "CR-W103"]
    for flag in body["flags"]:
        assert flag["refs"] and all(r["line_ids"] for r in flag["refs"]), flag["code"]
    orion = next(f for f in body["flags"] if f["code"] == "CR-W103")
    assert "Orion Mortgage" in orion["message"] and orion["refs"][0]["field"] == "inquiry_002"
    stored = await rows(session, "SELECT feature, code FROM flags WHERE feature = 'credit'")
    assert len(stored) == 4


async def test_alerts_come_first_and_are_flagged(
    docs_client: httpx.AsyncClient,
    session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await seed_report(session, alerts={"alerts": "Fraud alert on file"})

    body = await analyse(docs_client, session_factory)

    assert [a["code"] for a in body["alerts"]] == ["CR-W105"]
    assert "CR-W105" not in [f["code"] for f in body["flags"]]
    assert body["summary"][0] == "Alerts on the report: Fraud alert on file."


async def test_every_figure_is_stored_with_its_working_and_the_rows_keep_their_lines(
    docs_client: httpx.AsyncClient,
    session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await seed_report(session)

    body = await analyse(docs_client, session_factory)

    stored = await rows(
        session, "SELECT working FROM calculations WHERE run_id = :r", r=uuid.UUID(body["id"])
    )
    assert stored and all(r.working for r in stored)
    assert all(c["config_version"].startswith("thresholds@") for c in body["calculations"])
    assert len(await rows(session, "SELECT id FROM tradelines")) == 5
    assert len(await rows(session, "SELECT id FROM credit_scores")) == 3
    assert len(await rows(session, "SELECT id FROM credit_inquiries")) == 2
    assert all(t["line_ids"] for t in body["tradelines"])
    event = (
        await rows(session, "SELECT after FROM audit_events WHERE action = 'credit.analysed'")
    )[0]
    assert event.after["representative_score"] == "705" and event.after["tradelines"] == 5


async def test_a_second_run_is_a_new_run_and_the_first_stays(
    docs_client: httpx.AsyncClient,
    session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await seed_report(session)
    first = await analyse(docs_client, session_factory)

    second = await analyse(docs_client, session_factory)

    assert first["id"] != second["id"]
    assert len(await rows(session, "SELECT id FROM analysis_runs WHERE feature = 'credit'")) == 2
    assert len(await rows(session, "SELECT id FROM tradelines")) == 10  # five per run


async def test_a_corrected_value_is_what_the_analysis_uses(
    docs_client: httpx.AsyncClient,
    session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await seed_report(session, fixed={"tradeline_001_balance": "1000.00"})

    body = await analyse(docs_client, session_factory)

    northgate = tradeline(body, "Northgate Card")
    assert northgate["utilization"]["working"] == "1,000.00 / 8,000.00 = 12.50%"
    assert northgate["utilization_over_review_level"] is False
    assert "CR-W101" not in [f["code"] for f in body["flags"]]


async def test_with_no_credit_report_it_says_what_it_cannot_compute(
    docs_client: httpx.AsyncClient,
    session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    body = await analyse(docs_client, session_factory)

    assert body["status"] == "succeeded"
    assert body["representative"] is None and body["scores"] == [] and body["tradelines"] == []
    assert [f["code"] for f in body["flags"]] == ["CR-I101"]
    assert "Cannot compute the credit analysis" in body["flags"][0]["message"]


async def test_a_worker_that_fails_marks_the_job_and_run_failed_and_leaks_no_text(
    docs_client: httpx.AsyncClient,
    session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services import credit_runs

    def broken(*_: Any, **__: Any) -> Any:
        raise RuntimeError("Daniel Reyes Northgate Card 2,940.00")

    await seed_report(session)
    monkeypatch.setattr(credit_runs, "analyze", broken)

    response = await start(docs_client)
    accepted = response.json()
    await run_credit_analysis(
        {"session_factory": session_factory}, accepted["job"]["id"], accepted["analysis_id"]
    )

    job = (await rows(session, "SELECT status, error FROM jobs"))[0]
    assert (
        job.status == "failed" and job.error == "The credit report analysis could not be completed."
    )
    assert "Northgate" not in job.error
    assert (await latest(docs_client))["status"] == "failed"


async def test_a_queue_that_is_down_is_a_503_and_the_job_is_marked_failed(
    docs_client: httpx.AsyncClient, session: AsyncSession, fake_queue: FakeQueue
) -> None:
    fake_queue.fail = True

    response = await start(docs_client)

    assert (response.status_code, response.json()["code"]) == (503, "queue_unavailable")
    assert (await rows(session, "SELECT status FROM jobs"))[0].status == "failed"


# --- who may see it ---------------------------------------------------------------------------


async def test_the_admin_reads_it_and_the_specialist_cannot_see_a_pillar_1_case(
    docs_client: httpx.AsyncClient,
    session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await seed_report(session)
    await analyse(docs_client, session_factory)

    assert (await docs_client.get(f"{BASE}/latest", headers=headers(Role.ADMIN))).status_code == 200
    assert (
        await docs_client.get(f"{BASE}/latest", headers=headers(Role.LM_SPECIALIST))
    ).status_code == 404
    assert (await start(docs_client, Role.LM_SPECIALIST)).status_code == 404


async def test_no_token_is_a_401_a_bad_case_is_a_404_and_nothing_run_is_a_404(
    docs_client: httpx.AsyncClient,
) -> None:
    assert (await docs_client.post(BASE)).status_code == 401
    assert (await docs_client.get(f"{BASE}/latest")).status_code == 401
    bad = "/api/v1/cases/nope/credit-analysis"
    assert (await docs_client.post(bad, headers=headers())).status_code == 404
    assert (await docs_client.get(f"{bad}/latest", headers=headers())).status_code == 404
    assert (await docs_client.get(f"{BASE}/latest", headers=headers())).status_code == 404


async def test_no_text_says_approve_deny_offer_eligible_or_qualifies(
    docs_client: httpx.AsyncClient,
    session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await seed_report(session, alerts={"alerts": "Fraud alert on file"})

    body = await analyse(docs_client, session_factory)

    assert BLOCKED.search(json.dumps(body)) is None

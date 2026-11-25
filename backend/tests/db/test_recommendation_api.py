"""The loss mitigation rules through the API, the worker and Postgres (Feature Design 8, D7).

Angela Whitfield's documents are stored as the reader leaves them (the same helpers as the budget
tests) with her simulated loan record. ``POST /lm-recommendation`` queues the rules, the worker
applies the rule set in plain code (no model), and ``GET .../latest`` shows the waterfall and the
lender view. The figures must match the Feature Design to the cent. A judgement nobody confirmed is
reported as needing confirmation, a person's override stays beside the rules' own status and
carries to the next evaluation, and only the loss mitigation specialist starts the rules.
"""

from __future__ import annotations

import json
import re
import uuid
from typing import Any

import httpx
import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.demo.hardship import seed_hardship_profile
from app.db.demo.loan_record import seed_loan_record
from app.db.enums import ReportKind, Role
from app.db.models import AnalysisRun
from app.db.seed import case_id, seed
from app.services import report_writer
from app.services.report_writer import ReportDraft
from app.worker import run_recommendation_rules
from tests.db.conftest import FakeQueue, auth_headers
from tests.db.test_hardship_budget_api import DATA, read_letter, seed_documents
from tests.db.test_hardship_budget_api import latest as latest_assessment

ANGELA = case_id("Angela Whitfield — hardship")
DANIEL = case_id("Daniel Reyes — purchase")
BASE = f"/api/v1/cases/{ANGELA}/lm-recommendation"
HARDSHIP = f"/api/v1/cases/{ANGELA}/hardship-assessment"
LENDER = DATA["expected"]["lender_view"]
BLOCKED = re.compile(r"\b(approve[sd]?|deny|denied|offer(s|ed)?|eligible|qualifies)\b", re.I)


@pytest.fixture(autouse=True)
async def seeded(session: AsyncSession) -> None:
    await seed(session, "demo-pass")


def headers(role: Role = Role.LM_SPECIALIST) -> dict[str, str]:
    return auth_headers(role)


def _specialist() -> uuid.UUID:
    from app.db.seed import user_id

    return user_id("lm_specialist")


async def start(client: httpx.AsyncClient, role: Role = Role.LM_SPECIALIST) -> httpx.Response:
    return await client.post(BASE, headers=headers(role))


async def evaluate(
    client: httpx.AsyncClient, factory: async_sessionmaker[AsyncSession]
) -> dict[str, Any]:
    """Queue the rules, run the worker, and return what ``/latest`` then shows."""
    response = await start(client)
    assert response.status_code == 202, response.text
    await run_recommendation_rules(
        {"session_factory": factory}, response.json()["job"]["id"], str(_specialist())
    )
    return await latest(client)


async def latest(client: httpx.AsyncClient, role: Role = Role.LM_SPECIALIST) -> dict[str, Any]:
    response = await client.get(f"{BASE}/latest", headers=headers(role))
    assert response.status_code == 200, response.text
    return response.json()  # type: ignore[no-any-return]


async def confirm(client: httpx.AsyncClient, body: dict[str, Any]) -> None:
    response = await client.put(f"{HARDSHIP}/latest/confirmations", json=body, headers=headers())
    assert response.status_code == 200, response.text


async def ready(
    client: httpx.AsyncClient, session: AsyncSession, factory: async_sessionmaker[AsyncSession]
) -> None:
    """Documents stored, the letter read, the budget built, the loan record in place."""
    await seed_documents(session)
    await seed_loan_record(session, ANGELA, DATA["loan_record"])
    await read_letter(client, factory)


def option(body: dict[str, Any], name: str) -> dict[str, Any]:
    return next(o for o in body["waterfall"] if o["option"] == name)


def condition(body: dict[str, Any], condition_id: str) -> dict[str, Any]:
    return next(c for o in body["waterfall"] for c in o["conditions"] if c["id"] == condition_id)


def statuses(body: dict[str, Any]) -> dict[str, str]:
    return {o["option"]: o["status"] for o in body["waterfall"]}


def figure(body: dict[str, Any], name: str) -> dict[str, Any]:
    return next(f for f in body["lender_view"]["figures"] if f["name"] == name)


async def rows(session: AsyncSession, sql: str, **params: Any) -> list[Any]:
    return list((await session.execute(sa.text(sql), params)).all())


def override_url(condition_id: str) -> str:
    return f"{BASE}/latest/conditions/{condition_id}/override"


# --- starting the rules ----------------------------------------------------------------------


async def test_starting_queues_a_job_and_nothing_is_stored_until_the_worker_runs(
    docs_client: httpx.AsyncClient,
    session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
    fake_queue: FakeQueue,
) -> None:
    await ready(docs_client, session, session_factory)
    fake_queue.calls.clear()

    response = await start(docs_client)

    assert response.status_code == 202
    job = response.json()["job"]
    assert job["kind"] == "lm_recommendation" and job["status"] == "queued"
    assert fake_queue.calls == [
        ("run_recommendation_rules", (job["id"], str(_specialist())), job["id"])
    ]
    # No run exists yet, so "latest" is not an empty waterfall of a run still to be made.
    assert (await docs_client.get(f"{BASE}/latest", headers=headers())).status_code == 404
    assert [r.action for r in await rows(session, "SELECT action FROM audit_events")].count(
        "lm.rules_requested"
    ) == 1


async def test_the_worker_stores_the_waterfall_and_the_lender_view_to_the_cent(
    docs_client: httpx.AsyncClient,
    session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await ready(docs_client, session, session_factory)
    await confirm(docs_client, {"duration": {}, "intent": {}})

    body = await evaluate(docs_client, session_factory)

    assert body["source"] == "rules_engine" and body["notice"] is None
    assert body["run_status"] == "succeeded" and body["report"] is None
    assert statuses(body) == {
        "repayment_plan": "not_met",
        "forbearance": "not_met",
        "payment_deferral": "not_met",
        "loan_modification": "met",
        "short_sale": "not_reached",
        "deed_in_lieu": "not_reached",
    }
    assert [o["order_no"] for o in body["waterfall"]] == [1, 2, 3, 4, 5, 6]
    lender = body["lender_view"]
    assert (lender["foreclosure_loss"], lender["modification_cost"], lender["advantage"]) == (
        "16310.00",
        "13893.00",
        "2417.00",
    )
    assert lender["settings"] == LENDER["settings"]
    assert figure(body, "foreclosure_claim")["working"] == "212,400.00 + 5,160.00 = 217,560.00"
    assert figure(body, "target_payment")["value"] == "1470.00"
    assert figure(body, "modification_advantage")["working"] == ("16,310.00 - 13,893.00 = 2,417.00")


async def test_each_condition_shows_its_values_its_passage_and_where_each_figure_was_read(
    docs_client: httpx.AsyncClient,
    session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await ready(docs_client, session, session_factory)
    await confirm(docs_client, {"duration": {}, "intent": {}})

    body = await evaluate(docs_client, session_factory)

    surplus = condition(body, "repayment_plan.surplus")
    assert surplus["values"] == {"surplus": "-70.00", "arrears": "5160.00", "needed": "860.00"}
    assert surplus["passage_id"] == "sample-investor-a-v1.repayment-plan.2"
    target = condition(body, "loan_modification.target_payment")
    assert target["values"] == {
        "gross_monthly_income": "4200.00",
        "target_payment": "1470.00",
        "contractual_payment": "1720.00",
    }
    delinquent = condition(body, "payment_deferral.months_delinquent")
    assert delinquent["status"] == "met" and delinquent["values"]["months_delinquent"] == "3"
    assert delinquent["evidence"][0]["field"] == "months_delinquent"
    assert delinquent["evidence"][0]["label"] == "simulated servicing record"
    payment = [e for e in target["evidence"] if e.get("field") == "regular_monthly_payment"]
    assert payment and payment[0]["line_ids"] == ["p1-L12"]  # a line of the mortgage statement
    assert any(e.get("name") == "documented_gross_monthly_income" for e in target["evidence"])
    assert condition(body, "short_sale.reached")["derived"] is True
    # The passage opens in the guideline reader.
    passage = await docs_client.get(
        f"/api/v1/guidelines/passages/{target['passage_id']}", headers=headers()
    )
    assert passage.status_code == 200 and passage.json()["id"] == target["passage_id"]


async def test_the_run_records_the_rule_set_it_used_and_every_figure_is_stored_with_working(
    docs_client: httpx.AsyncClient,
    session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await ready(docs_client, session, session_factory)
    await confirm(docs_client, {"duration": {}, "intent": {}})

    body = await evaluate(docs_client, session_factory)

    rule_set = body["rule_set"]
    assert (rule_set["name"], rule_set["version"], rule_set["label"]) == (
        "Sample Investor A",
        "1",
        "illustrative",
    )
    assert rule_set["banner"] == "Illustrative: not an actual investor's requirements."
    version = (await rows(session, "SELECT * FROM config_versions WHERE kind = 'rule_set'"))[0]
    assert (version.name, version.version, version.label, version.active) == (
        "Sample Investor A",
        "1",
        "illustrative",
        True,
    )
    run = (
        await rows(
            session,
            "SELECT config_versions FROM analysis_runs WHERE id = :id",
            id=uuid.UUID(body["run_id"]),
        )
    )[0]
    assert run.config_versions["rule_set"]["hash"] == version.content_hash
    stored = await rows(
        session,
        "SELECT name, working FROM calculations WHERE run_id = :id",
        id=uuid.UUID(body["run_id"]),
    )
    assert {r.name for r in stored} >= {
        "target_payment",
        "repayment_plan_surplus_needed",
        "foreclosure_loss",
        "modification_advantage",
    }
    assert all(r.working for r in stored)
    event = (await rows(session, "SELECT * FROM audit_events WHERE action = 'lm.rules_evaluated'"))[
        0
    ]
    assert event.after["options"]["loan_modification"] == "met"


# --- judgements nobody has confirmed -----------------------------------------------------------


async def test_unconfirmed_judgements_need_confirmation_until_a_person_confirms_them(
    docs_client: httpx.AsyncClient,
    session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await ready(docs_client, session, session_factory)

    first = await evaluate(docs_client, session_factory)

    assert statuses(first)["loan_modification"] == "needs_confirmation"
    assert statuses(first)["forbearance"] == "needs_confirmation"
    assert statuses(first)["repayment_plan"] == "not_met"  # the figure fails whatever the duration
    hardship = condition(first, "loan_modification.hardship_long_term")
    assert hardship["status"] == "needs_confirmation"
    assert hardship["values"] == {"duration": "unknown", "confirmed": "no"}
    assert statuses(first)["short_sale"] == "needs_confirmation"

    await confirm(docs_client, {"duration": {}, "intent": {}})
    second = await evaluate(docs_client, session_factory)

    assert statuses(second)["loan_modification"] == "met"
    assert statuses(second)["short_sale"] == "not_reached"


async def test_a_corrected_duration_is_what_the_rules_use_and_the_letters_reading_stays(
    docs_client: httpx.AsyncClient,
    session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await ready(docs_client, session, session_factory)
    await confirm(
        docs_client,
        {
            "duration": {"value": "temporary", "reason": "Her employer confirmed hours return"},
            "intent": {},
        },
    )

    body = await evaluate(docs_client, session_factory)

    assert condition(body, "forbearance.hardship_temporary")["status"] == "met"
    assert statuses(body)["forbearance"] == "met"
    assert statuses(body)["loan_modification"] == "not_reached"  # the waterfall stopped earlier
    assert (await latest_assessment(docs_client))["profile"]["duration"]["category"] == "unknown"


# --- a person's override ----------------------------------------------------------------------


async def test_an_override_recomputes_the_waterfall_and_carries_to_the_next_evaluation(
    docs_client: httpx.AsyncClient,
    session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await ready(docs_client, session, session_factory)
    await confirm(docs_client, {"duration": {}, "intent": {}})
    await evaluate(docs_client, session_factory)

    overridden = await docs_client.put(
        override_url("forbearance.hardship_temporary"),
        json={"status": "met", "reason": "Employer letter says the hours return in January"},
        headers=headers(),
    )

    assert overridden.status_code == 200, overridden.text
    assert statuses(overridden.json())["forbearance"] == "met"
    assert statuses(overridden.json())["loan_modification"] == "not_reached"

    again = await evaluate(docs_client, session_factory)

    held = condition(again, "forbearance.hardship_temporary")
    assert held["status"] == "not_met"  # what the rules now find, unchanged
    assert held["effective_status"] == "met"
    assert held["override"]["reason"] == "Employer letter says the hours return in January"
    assert held["override"]["by"] == str(_specialist())
    assert option(again, "forbearance")["status"] == "met"
    assert option(again, "forbearance")["original_status"] == "not_met"
    assert option(again, "forbearance")["overridden"] is True
    assert statuses(again)["loan_modification"] == "not_reached"
    event = (
        await rows(session, "SELECT after FROM audit_events WHERE action = 'lm.rules_evaluated'")
    )[-1]
    assert event.after["overrides_carried"] == ["forbearance.hardship_temporary"]


async def test_an_override_the_rules_have_caught_up_with_is_dropped_not_kept(
    docs_client: httpx.AsyncClient,
    session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await ready(docs_client, session, session_factory)
    await confirm(docs_client, {"duration": {}, "intent": {}})
    await evaluate(docs_client, session_factory)
    await docs_client.put(
        override_url("forbearance.hardship_temporary"),
        json={"status": "met", "reason": "Employer letter"},
        headers=headers(),
    )
    await confirm(docs_client, {"duration": {"value": "temporary", "reason": "Confirmed"}})

    body = await evaluate(docs_client, session_factory)

    caught_up = condition(body, "forbearance.hardship_temporary")
    assert caught_up["status"] == "met" and caught_up["override"] is None
    assert option(body, "forbearance")["overridden"] is False


async def test_a_derived_condition_cannot_be_overridden_on_a_rules_run(
    docs_client: httpx.AsyncClient,
    session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await ready(docs_client, session, session_factory)
    await evaluate(docs_client, session_factory)

    response = await docs_client.put(
        override_url("short_sale.reached"),
        json={"status": "met", "reason": "x"},
        headers=headers(),
    )

    assert (response.status_code, response.json()["code"]) == (422, "derived_condition")


# --- sign-off needs a report of this evaluation -----------------------------------------------


async def test_the_rules_write_no_report_so_there_is_nothing_to_sign_off_until_the_agents_do(
    docs_client: httpx.AsyncClient,
    session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await ready(docs_client, session, session_factory)
    await confirm(docs_client, {"duration": {}, "intent": {}})
    body = await evaluate(docs_client, session_factory)

    refused = await docs_client.post(f"{BASE}/latest/sign-off", json={}, headers=headers())

    assert (refused.status_code, refused.json()["code"]) == (409, "no_report")

    run = await session.get(AnalysisRun, uuid.UUID(body["run_id"]))
    assert run is not None
    await report_writer.write_report(
        session,
        run,
        ReportKind.LM_RECOMMENDATION,
        ReportDraft(sections={"note": "Stand-in for the agents' draft."}),
    )
    signed = await docs_client.post(
        f"{BASE}/latest/sign-off", json={"note": "Checked the waterfall"}, headers=headers()
    )

    assert signed.status_code == 201, signed.text
    assert signed.json()["sign_off"]["statement"] == "Records a review. Not a decision."


async def test_an_older_runs_report_is_not_signed_off_for_a_newer_waterfall(
    docs_client: httpx.AsyncClient,
    session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    from app.db.demo.reports import seed_lm_recommendation

    await ready(docs_client, session, session_factory)
    await seed_lm_recommendation(session, ANGELA)
    seeded = await latest(docs_client)
    assert seeded["source"] == "seeded_sample"
    await evaluate(docs_client, session_factory)

    response = await docs_client.post(f"{BASE}/latest/sign-off", json={}, headers=headers())

    assert (response.status_code, response.json()["code"]) == (409, "no_report")


# --- what is missing --------------------------------------------------------------------------


async def test_with_no_documents_each_condition_says_what_it_needs_and_there_is_no_lender_view(
    docs_client: httpx.AsyncClient,
    session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await seed_hardship_profile(session, ANGELA)

    body = await evaluate(docs_client, session_factory)

    surplus = condition(body, "repayment_plan.surplus")
    assert surplus["status"] == "not_evaluable"
    assert surplus["note"] == "Needs the hardship budget's monthly surplus or deficit."
    assert body["lender_view"] is None
    assert condition(body, "payment_deferral.months_delinquent")["status"] == "not_evaluable"
    assert statuses(body)["loan_modification"] != "met"


async def test_with_no_letter_read_the_judgements_are_not_evaluable(
    docs_client: httpx.AsyncClient,
    session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    body = await evaluate(docs_client, session_factory)

    assert condition(body, "forbearance.hardship_temporary")["status"] == "not_evaluable"
    assert statuses(body)["loan_modification"] == "not_evaluable"


async def test_the_loan_record_supplies_months_delinquent_when_no_statement_was_read(
    docs_client: httpx.AsyncClient,
    session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await seed_hardship_profile(session, ANGELA)
    await seed_loan_record(session, ANGELA, DATA["loan_record"])

    body = await evaluate(docs_client, session_factory)

    assert condition(body, "payment_deferral.months_delinquent")["status"] == "met"
    needed = condition(body, "repayment_plan.surplus")
    assert needed["status"] == "not_evaluable"  # still no budget, so no surplus
    assert body["lender_view"] is None  # no income, so no target payment


async def test_a_worker_that_fails_marks_the_job_failed_and_stores_no_run_and_no_text(
    docs_client: httpx.AsyncClient,
    session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services import recommendation_runs

    async def broken(*_: Any, **__: Any) -> Any:
        raise RuntimeError("Angela Whitfield 5,160.00 PINEBROOK")

    monkeypatch.setattr(recommendation_runs, "gather_inputs", broken)
    response = await start(docs_client)
    await run_recommendation_rules(
        {"session_factory": session_factory},
        response.json()["job"]["id"],
        str(_specialist()),
    )

    job = (await rows(session, "SELECT status, error FROM jobs"))[0]
    assert job.status == "failed" and job.error == "The rules could not be applied to this case."
    assert "Whitfield" not in job.error and "5,160" not in job.error
    assert (
        await rows(session, "SELECT id FROM analysis_runs WHERE feature = 'lm_recommendation'")
        == []
    )


async def test_a_queue_that_is_down_is_a_503_and_the_job_is_marked_failed(
    docs_client: httpx.AsyncClient, session: AsyncSession, fake_queue: FakeQueue
) -> None:
    fake_queue.fail = True

    response = await start(docs_client)

    assert (response.status_code, response.json()["code"]) == (503, "queue_unavailable")
    assert (await rows(session, "SELECT status FROM jobs"))[0].status == "failed"


# --- who may do what --------------------------------------------------------------------------


async def test_only_the_specialist_starts_the_rules_and_everyone_else_gets_403(
    docs_client: httpx.AsyncClient,
    session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await ready(docs_client, session, session_factory)

    for role in (Role.ADMIN, Role.UNDERWRITER):
        assert (await start(docs_client, role)).status_code == 403
    assert await rows(session, "SELECT id FROM jobs WHERE kind = 'lm_recommendation'") == []


async def test_the_admin_reads_the_result_and_the_underwriter_cannot_see_the_case(
    docs_client: httpx.AsyncClient,
    session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await ready(docs_client, session, session_factory)
    await evaluate(docs_client, session_factory)

    assert (await docs_client.get(f"{BASE}/latest", headers=headers(Role.ADMIN))).status_code == 200
    assert (
        await docs_client.get(f"{BASE}/latest", headers=headers(Role.UNDERWRITER))
    ).status_code == 404


async def test_a_pillar_1_case_is_a_404_for_the_specialist_and_no_token_is_a_401(
    docs_client: httpx.AsyncClient,
) -> None:
    daniel = f"/api/v1/cases/{DANIEL}/lm-recommendation"

    assert (await docs_client.post(daniel, headers=headers())).status_code == 404
    assert (await docs_client.post(BASE)).status_code == 401
    assert (
        await docs_client.post("/api/v1/cases/nope/lm-recommendation", headers=headers())
    ).status_code == 404


async def test_a_case_with_no_evaluation_has_nothing_to_override(
    docs_client: httpx.AsyncClient,
) -> None:
    response = await docs_client.put(
        override_url("forbearance.hardship_temporary"),
        json={"status": "met", "reason": "x"},
        headers=headers(),
    )

    assert response.status_code == 404


async def test_no_text_in_the_recommendation_says_approve_deny_offer_eligible_or_qualifies(
    docs_client: httpx.AsyncClient,
    session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await ready(docs_client, session, session_factory)
    await confirm(docs_client, {"duration": {}, "intent": {}})

    body = await evaluate(docs_client, session_factory)

    assert BLOCKED.search(json.dumps(body)) is None

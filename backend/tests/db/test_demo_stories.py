"""The two demo stories, upload to sign-off, through the HTTP API (D7, C12).

Everything a person would do goes through the API: log in, upload the borrower's documents, run each
analysis, confirm and correct, review, sign off, read the audit trail. The only things that are not
HTTP are the workers (run in-process, as ``make reset-demo`` does, because there is no Redis here)
and the stand-ins for work that is not ours: the rule-based reader instead of a model, Arindam's
worked example instead of his hardship reading, the keyword labeller, and a hand-written report
where the agents will write one. Every figure is checked against the Feature Design and the
scenario's ``expected`` block, to the cent.

Daniel Reyes (Pillar 1, underwriter): income, completeness, loan scenario, assets and DTI 44.70%,
credit analysis, the draft report's conditions, sign-off.
Angela Whitfield (Pillar 2, loss mitigation specialist): hardship reading, confirmations, budget,
the investor's rules, an override, sign-off.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.demo.loan_record import seed_loan_record
from app.db.demo.reports import seed_underwriting_report
from app.db.enums import ReportKind, Role
from app.db.models import AnalysisRun
from app.db.seed import DEMO_USERS, case_id, seed
from app.services import report_writer
from app.services.fake_reader import FakeClassifier, FakeExtractor
from app.services.ingestion_config import get_ingestion_config
from app.services.report_writer import ReportDraft
from app.services.transaction_labels import FakeLabeller
from app.storage import Storage
from app.worker import (
    process_documents,
    run_asset_analysis,
    run_credit_analysis,
    run_hardship_reading,
    run_income_analysis,
    run_recommendation_rules,
)
from tests.conftest import Rendered
from tests.db.conftest import FakeQueue
from tests.db.test_documents_api import upload
from tests.db.test_hardship_budget_api import StubReader

DANIEL = case_id("Daniel Reyes — purchase")
ANGELA = case_id("Angela Whitfield — hardship")
SCENARIOS = Path(__file__).resolve().parents[3] / "data" / "synthetic" / "scenarios"
DANIEL_DATA: dict[str, Any] = json.loads((SCENARIOS / "daniel_reyes.json").read_text("utf-8"))
ANGELA_DATA: dict[str, Any] = json.loads((SCENARIOS / "angela_whitfield.json").read_text("utf-8"))
CONFIG = get_ingestion_config().model_copy(update={"render_dpi": 50})
BLOCKED = re.compile(r"\b(approve[sd]?|deny|denied|offer(s|ed)?|eligible|qualifies)\b", re.I)
PASSWORD = "demo-pass"
USERS = {role.value: username for username, _, role in DEMO_USERS}


@pytest.fixture(autouse=True)
async def seeded(session: AsyncSession) -> None:
    await seed(session, PASSWORD)


class Person:
    """A user of the demo, signed in through the API like the frontend does."""

    def __init__(self, client: httpx.AsyncClient, role: Role, token: str) -> None:
        self.client, self.role, self.headers = client, role, {"Authorization": f"Bearer {token}"}
        self.user_id = ""

    async def get(self, path: str, **params: Any) -> httpx.Response:
        return await self.client.get(f"/api/v1{path}", headers=self.headers, params=params)

    async def post(self, path: str, body: Any = None) -> httpx.Response:
        return await self.client.post(f"/api/v1{path}", headers=self.headers, json=body)

    async def put(self, path: str, body: Any) -> httpx.Response:
        return await self.client.put(f"/api/v1{path}", headers=self.headers, json=body)

    async def patch(self, path: str, body: Any) -> httpx.Response:
        return await self.client.patch(f"/api/v1{path}", headers=self.headers, json=body)


async def sign_in(client: httpx.AsyncClient, role: Role) -> Person:
    response = await client.post(
        "/api/v1/auth/login", json={"username": USERS[role.value], "password": PASSWORD}
    )
    assert response.status_code == 200, response.text
    body = response.json()
    person = Person(client, role, body["access_token"])
    person.user_id = body["user"]["id"]
    return person


def ok(response: httpx.Response, status: int = 200) -> Any:
    assert response.status_code == status, response.text
    return response.json()


async def upload_and_read(
    person: Person,
    case: Any,
    rendered: Rendered,
    folder: str,
    storage: Storage,
    factory: async_sessionmaker[AsyncSession],
) -> list[dict[str, Any]]:
    """Upload every clean PDF of the borrower's folder, then run the pipeline worker on them."""
    names = sorted(p.name for p in rendered.path(folder).glob("*.pdf"))
    files = [(name, rendered.read(f"{folder}/{name}")) for name in names]
    response = await upload(person.client, case, files, role=person.role)
    body = ok(response, 202)
    await process_documents(
        {
            "storage": storage,
            "session_factory": factory,
            "ingestion_config": CONFIG,
            "classifier": FakeClassifier(),
            "extractor": FakeExtractor(),
        },
        body["job"]["id"],
        [d["id"] for d in body["documents"]],
        None,
        False,
    )
    listed = ok(await person.get(f"/cases/{case}/documents"))
    return listed["items"]  # type: ignore[no-any-return]


def audit_actions(events: dict[str, Any]) -> list[str]:
    return [e["action"] for e in events["items"]]


# --- Daniel Reyes: purchase, underwriter ------------------------------------------------------


async def test_daniels_story_from_upload_to_sign_off(
    docs_client: httpx.AsyncClient,
    session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
    s3_storage: Storage,
    rendered: Rendered,
    fake_queue: FakeQueue,
) -> None:
    daniel = await sign_in(docs_client, Role.UNDERWRITER)
    ctx: dict[str, Any] = {"session_factory": session_factory, "labeller": FakeLabeller()}
    case = DANIEL

    # 1. Upload and read his documents (the rule-based reader stands in for the model).
    items = await upload_and_read(
        daniel, case, rendered, "daniel_reyes", s3_storage, session_factory
    )
    types = sorted(d["doc_type"] for d in items)
    assert types == [
        "bank_statement",
        "bank_statement",
        "credit_report",
        "expense_bill",
        "pay_stub",
        "tax_return_1040",
        "w2",
    ]
    assert not [d for d in items if d["status"] in ("uploaded", "processing", "failed")]
    stub = next(d for d in items if d["doc_type"] == "pay_stub")
    assert stub["status"] == "needs_review"  # the printed net pay does not add up (demo step 3)

    # 2. Income.
    queued = ok(await daniel.post(f"/cases/{case}/income-analysis"), 202)
    await run_income_analysis(ctx, queued["job"]["id"], queued["analysis_id"])
    income = ok(await daniel.get(f"/cases/{case}/income-analysis/latest"))
    assert income["status"] == "succeeded" and income["candidate"]["value"]

    # 3. He enters the case profile, then checks completeness against the purchase checklist.
    ok(
        await daniel.put(
            f"/cases/{case}/profile",
            {
                "borrower_names": ["Daniel Reyes"],
                "employment_type": "wage_earner",
                "reference_date": DANIEL_DATA["borrower"]["reference_date"],
            },
        )
    )
    check = ok(
        await daniel.post(f"/cases/{case}/completeness", {"checklist_id": "pillar1-wage-earner@1"})
    )
    assert check["checklist_label"] == "illustrative" and check["items"]

    # 4. The loan scenario, then assets, liabilities and DTI.
    loan = DANIEL_DATA["loan_scenario"]
    scenario = {
        "purpose": loan["purpose"],
        "occupancy": loan["occupancy"],
        "property_value": loan["property_value"],
        "loan_amount": loan["loan_amount"],
        "proposed_housing_payment": loan["proposed_housing_payment"],
        "funds_to_close": loan["funds_needed_to_close"],
    }
    ok(await daniel.put(f"/cases/{case}/loan-scenario", scenario))
    queued = ok(await daniel.post(f"/cases/{case}/asset-liability"), 202)
    await run_asset_analysis(ctx, queued["job"]["id"], queued["analysis_id"])
    assets = ok(await daniel.get(f"/cases/{case}/asset-liability/latest"))
    expected = DANIEL_DATA["expected"]["assets_liabilities"]
    assert assets["documented_assets"]["value"] == expected["documented_assets"] == "9226.32"
    assert assets["funds_shortfall"]["value"] == expected["shortfall"] == "27273.68"
    assert assets["ltv"]["working"].endswith("90.00%")
    # The credit report was read by the same pipeline, so the debts reconcile with the bank
    # statements: 693.00 a month, and DTI 44.70% (Feature Design 3.8).
    assert assets["monthly_obligations"]["value"] == expected["obligations_monthly"] == "693.00"
    assert assets["dti"]["working"].endswith(f"{expected['dti_pct']}%"), assets["dti"]["working"]
    assert assets["front_end_ratio"]["working"].endswith(f"{expected['front_end_ratio_pct']}%")
    assert any(f["code"] == "AL-W106" for f in assets["flags"])  # DTI above the review level

    # 5. The credit report analysis.
    queued = ok(await daniel.post(f"/cases/{case}/credit-analysis"), 202)
    await run_credit_analysis(ctx, queued["job"]["id"], queued["analysis_id"])
    credit = ok(await daniel.get(f"/cases/{case}/credit-analysis/latest"))
    assert credit["representative"]["score"] == 705
    northgate = next(t for t in credit["tradelines"] if t["creditor"] == "Northgate Card")
    assert northgate["utilization"]["working"] == "2,940.00 / 8,000.00 = 36.75%"
    assert credit["total_revolving_utilization"]["working"].endswith("28.00%")
    payments = {c["name"]: c["value"] for c in credit["monthly_payments"]}
    assert payments["monthly_payments_total"] == "693.00"
    assert credit["summary"][0].startswith("One 30-day late payment on Northgate Card, 19 months")

    # 6. The draft report is hand-written until the agents write one. The underwriter reviews its
    # six conditions: accepts five, rejects one with a reason, and signs off.
    await seed_underwriting_report(session, case)
    await session.commit()
    report = ok(await daniel.get(f"/cases/{case}/underwriting-report/latest"))
    assert report["report"]["source"] == "seeded_sample" and len(report["conditions"]) == 6
    assert report["report"]["status"] == "draft"
    for condition in report["conditions"][:5]:
        ok(
            await daniel.patch(
                f"/cases/{case}/underwriting-report/latest/conditions/{condition['id']}",
                {"decision": "accepted"},
            )
        )
    last = report["conditions"][5]
    reviewed = ok(
        await daniel.patch(
            f"/cases/{case}/underwriting-report/latest/conditions/{last['id']}",
            {"decision": "rejected", "reason": "Not required for this file"},
        )
    )
    assert [c["decision"] for c in reviewed["conditions"]] == ["accepted"] * 5 + ["rejected"]
    assert reviewed["conditions"][5]["text"] == last["text"]  # what the agents wrote stays
    signed = ok(
        await daniel.post(
            f"/cases/{case}/underwriting-report/latest/sign-off", {"note": "Reviewed with DTI"}
        ),
        201,
    )
    assert signed["sign_off"]["statement"] == "Records a review. Not a decision."
    assert signed["report_status"] == "signed_off" and signed["pending_conditions"] == 0

    # 7. Every step is in the audit trail, newest first, with who did it.
    trail = ok(await daniel.get(f"/cases/{case}/audit", limit=200))
    actions = audit_actions(trail)
    assert actions[0] == "report.signed_off"
    for expected_action in (
        "income.run_requested",
        "income.analysed",
        "assets.run_requested",
        "credit.run_requested",
        "credit.analysed",
        "underwriting.condition_accepted",
        "underwriting.condition_rejected",
    ):
        assert expected_action in actions, expected_action
    assert BLOCKED.search(json.dumps([income, assets, credit, report, signed, trail])) is None


# --- Angela Whitfield: loss mitigation, specialist --------------------------------------------


async def test_angelas_story_from_upload_to_sign_off(
    docs_client: httpx.AsyncClient,
    session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
    s3_storage: Storage,
    rendered: Rendered,
) -> None:
    angela = await sign_in(docs_client, Role.LM_SPECIALIST)
    ctx: dict[str, Any] = {
        "session_factory": session_factory,
        "labeller": FakeLabeller(),
        "hardship_reader": StubReader(),
    }
    case = ANGELA
    base = f"/cases/{case}"
    # The servicing system is simulated: the loan record holds months delinquent.
    await seed_loan_record(session, case, ANGELA_DATA["loan_record"])
    await session.commit()

    # 1. Upload and read her documents.
    items = await upload_and_read(
        angela, case, rendered, "angela_whitfield", s3_storage, session_factory
    )
    assert "hardship_letter" in [d["doc_type"] for d in items] and len(items) == 8

    # 2. The hardship letter is read (Arindam's worked example stands in for the model) and the
    # budget is built on both bases from the documents the reader read.
    queued = ok(await angela.post(f"{base}/hardship-assessment"), 202)
    await run_hardship_reading(ctx, queued["job"]["id"], angela.user_id)
    assessment = ok(await angela.get(f"{base}/hardship-assessment/latest"))
    assert assessment["source"] == "model"
    measures = {m["name"]: m["value"] for m in assessment["measures"]}
    budget = ANGELA_DATA["expected"]["budget"]
    assert measures["documented_gross_monthly_income"] == "4200.00"
    assert measures["surplus_stated"] == f"-{budget['deficit_stated']}"
    assert measures["surplus_observed"] == f"-{budget['deficit_observed']}"
    assert measures["arrears"] == budget["arrears"] == "5160.00"
    other = next(b for b in assessment["budget"] if b["category"] == "Other")
    assert (other["stated"], other["observed"], other["flagged"]) == ("200.00", "410.00", True)
    assert assessment["profile"]["duration"]["confirmation"] is None

    # 3. Before she confirms the judgements, the rules do not use them.
    queued = ok(await angela.post(f"{base}/lm-recommendation"), 202)
    await run_recommendation_rules(ctx, queued["job"]["id"], angela.user_id)
    first = ok(await angela.get(f"{base}/lm-recommendation/latest"))
    assert {o["option"]: o["status"] for o in first["waterfall"]}["loan_modification"] == (
        "needs_confirmation"
    )

    # 4. She confirms the duration as read and the intent, then the rules run again.
    confirmed = ok(
        await angela.put(
            f"{base}/hardship-assessment/latest/confirmations", {"duration": {}, "intent": {}}
        )
    )
    assert confirmed["profile"]["intent"]["confirmation"]["label"] == "reviewer-confirmed"
    queued = ok(await angela.post(f"{base}/lm-recommendation"), 202)
    await run_recommendation_rules(ctx, queued["job"]["id"], angela.user_id)
    rec = ok(await angela.get(f"{base}/lm-recommendation/latest"))
    assert {o["option"]: o["status"] for o in rec["waterfall"]} == {
        "repayment_plan": "not_met",
        "forbearance": "not_met",
        "payment_deferral": "not_met",
        "loan_modification": "met",
        "short_sale": "not_reached",
        "deed_in_lieu": "not_reached",
    }
    lender = rec["lender_view"]
    expected = ANGELA_DATA["expected"]["lender_view"]
    assert lender["foreclosure_loss"] == expected["foreclosure"]["loss"] == "16310.00"
    assert lender["modification_cost"] == expected["modification"]["expected_cost"] == "13893.00"
    assert lender["advantage"] == expected["modification_advantage"] == "2417.00"
    assert rec["rule_set"]["banner"].startswith("Illustrative")
    plan = next(o for o in rec["waterfall"] if o["option"] == "repayment_plan")
    surplus = next(c for c in plan["conditions"] if c["id"] == "repayment_plan.surplus")
    assert surplus["values"] == {"surplus": "-70.00", "arrears": "5160.00", "needed": "860.00"}

    # 5. She overrides a condition with a reason: the statuses recompute and the rules' own
    # answer stays beside hers.
    overridden = ok(
        await angela.put(
            f"{base}/lm-recommendation/latest/conditions/forbearance.hardship_temporary/override",
            {"status": "met", "reason": "Her employer confirmed hours return in January"},
        )
    )
    forbearance = next(o for o in overridden["waterfall"] if o["option"] == "forbearance")
    assert (forbearance["status"], forbearance["original_status"]) == ("met", "not_met")
    assert (
        next(o for o in overridden["waterfall"] if o["option"] == "loan_modification")["status"]
        == "not_reached"
    )

    # 6. There is no report to sign off until the agents write one (a hand-written stand-in here).
    refused = await angela.post(f"{base}/lm-recommendation/latest/sign-off", {})
    assert (refused.status_code, refused.json()["code"]) == (409, "no_report")
    run = await session.get(AnalysisRun, rec["run_id"])
    assert run is not None
    await report_writer.write_report(
        session,
        run,
        ReportKind.LM_RECOMMENDATION,
        ReportDraft(sections={"note": "Stand-in for the agents' draft."}),
    )
    await session.commit()
    signed = ok(
        await angela.post(f"{base}/lm-recommendation/latest/sign-off", {"note": "Reviewed"}), 201
    )
    assert signed["sign_off"]["statement"] == "Records a review. Not a decision."

    # 7. The audit trail has it all, and nothing says anything is approved or offered.
    trail = ok(await angela.get(f"{base}/audit", limit=200))
    actions = audit_actions(trail)
    assert actions[0] == "report.signed_off"
    for expected_action in (
        "hardship.reading_requested",
        "hardship.confirmed",
        "lm.rules_requested",
        "lm.rules_evaluated",
        "lm.condition_overridden",
    ):
        assert expected_action in actions, expected_action
    assert BLOCKED.search(json.dumps([assessment, first, rec, overridden, signed, trail])) is None


async def test_the_two_stories_never_cross_pillars(
    docs_client: httpx.AsyncClient,
    session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    daniel = await sign_in(docs_client, Role.UNDERWRITER)
    angela = await sign_in(docs_client, Role.LM_SPECIALIST)

    for path in ("/income-analysis/latest", "/credit-analysis/latest", "/audit"):
        assert (await angela.get(f"/cases/{DANIEL}{path}")).status_code == 404, path
    for path in ("/hardship-assessment/latest", "/lm-recommendation/latest", "/audit"):
        assert (await daniel.get(f"/cases/{ANGELA}{path}")).status_code == 404, path
    assert (await daniel.post(f"/cases/{ANGELA}/lm-recommendation")).status_code == 403
    assert (await angela.post(f"/cases/{DANIEL}/credit-analysis")).status_code == 404

"""The agents (Feature Design 6.5 and 8.5) against a real database, with a fake model.

The fake answers by the output model it is asked for, so the number of Researcher questions does
not matter. The Writer's first draft carries a figure that is in no stored result and a decision
word; the code checks catch both, the draft goes back once, and anything still wrong is removed.
"""

from __future__ import annotations

import json
import uuid
from decimal import Decimal
from typing import Any

import httpx
import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.agents.jobs import run_agents_job
from app.agents.lm import run_lm_agents
from app.agents.underwriting import run_underwriting
from app.db.demo.hardship import seed_hardship_profile
from app.db.demo.loan_record import seed_loan_record
from app.db.enums import AgentName, AnalysisFeature, JobStatus, ReportKind, Role
from app.db.models import AgentRun, Calculation, Job
from app.db.seed import case_id, seed
from app.llm.gateway import Gateway
from app.llm.types import AdapterRequest, AdapterResponse
from app.services import flags as flag_service
from app.services import report_writer, reports
from app.services.recommendation_runs import run_recommendation_rules
from tests.db.conftest import FakeQueue, auth_headers
from tests.db.test_hardship_budget_api import DATA
from tests.llm.fakes import fake_config

DANIEL = case_id("Daniel Reyes — purchase")
ANGELA = case_id("Angela Whitfield — hardship")

BAD_DRAFT = {
    "conflicts": [
        {
            "title": "DTI with and without overtime",
            "detail": "DTI is 44.70%, or 41.61% if overtime is counted. The underwriter decides.",
            "evidence_refs": ["assets.dti", "assets.dti_with_overtime"],
        }
    ],
    "missing_information": ["Page 3 of the August 2026 bank statement (F2)."],
    "potential_risks": ["Assets are 12,345.67 short."],  # a figure in no stored result
    "conditions": [
        {
            "text": "Provide the source of the large transfer.",
            "priority": "significant",
            "finding_ids": ["F1"],
        },
        {
            "text": "The loan is eligible once page 3 arrives.",
            "priority": "attention",
            "finding_ids": ["F2"],
        },
    ],
}
GOOD_DRAFT = {
    **BAD_DRAFT,
    "potential_risks": ["Documented assets are short of the funds to close (F1)."],
    "conditions": [BAD_DRAFT["conditions"][0]],
}


class RoutingModel:
    """Replies by the output model asked for; records every request."""

    name = "fake"

    def __init__(self, writer_drafts: list[dict[str, Any]], critic: str = "pass") -> None:
        self.writer_drafts = writer_drafts
        self.critic = critic
        self.requests: list[AdapterRequest] = []

    async def complete(self, request: AdapterRequest) -> AdapterResponse:
        self.requests.append(request)
        name = request.output_model.__name__
        if name == "GuidelineAnswerResult":
            body: dict[str, Any] = {
                "status": "answered",
                "sentences": [
                    {"text": "The passage covers this point.", "citations": [1], "quote": None}
                ],
                "comparison": None,
                "facts_to_check": ["The date the application was received"],
            }
        elif name in ("UnderwritingDraft", "LmDraft"):
            body = (
                self.writer_drafts.pop(0) if len(self.writer_drafts) > 1 else self.writer_drafts[0]
            )
        elif name == "CriticVerdict":
            body = {"verdict": self.critic, "fixes": []}
        else:
            raise AssertionError(name)
        return AdapterResponse(text=json.dumps(body), input_tokens=10, output_tokens=10)

    def count(self, name: str) -> int:
        return sum(1 for r in self.requests if r.output_model.__name__ == name)


def gateway(model: RoutingModel) -> Gateway:
    return Gateway({"fake": model}, fake_config())


@pytest.fixture(autouse=True)
async def seeded(session: AsyncSession) -> None:
    await seed(session, "demo-pass")


async def stored_assets(session: AsyncSession) -> None:
    """A minimal asset run for Daniel: two DTI figures and two flags."""
    run = await report_writer.start_run(session, DANIEL, AnalysisFeature.ASSETS)
    for name, value, working in [
        ("dti", "0.447", "(1,980.00 + 693.00) / 5,980.00 = 44.70%"),
        ("dti_with_overtime", "0.4161", "(1,980.00 + 693.00) / 6,424.41 = 41.61%"),
        ("funds_shortfall", "27273.68", "36,500.00 - 9,226.32 = 27,273.68"),
    ]:
        session.add(
            Calculation(
                run_id=run.id,
                case_id=DANIEL,
                name=name,
                value=Decimal(value),
                unit="usd" if name == "funds_shortfall" else "ratio",
                formula=name,
                inputs={},
                working=working,
            )
        )
    for code, message in [
        ("AL-W105", "Documented assets of 9,226.32 are 27,273.68 short of the 36,500.00 needed."),
        ("DI-W701", "Incomplete: page 3 of the August 2026 statement is missing."),
    ]:
        await flag_service.raise_flag(
            session,
            case_id=DANIEL,
            entity_type="asset_check",
            entity_id=uuid.uuid4(),
            code=code,
            severity="warning",
            message=message,
            evidence={"run_id": str(run.id)},
            feature="assets",
        )
    await report_writer.finish_run(session, run)
    await session.flush()


async def test_underwriting_report_from_the_agents(session: AsyncSession) -> None:
    await stored_assets(session)
    model = RoutingModel([BAD_DRAFT, GOOD_DRAFT])

    report = await run_underwriting(session, DANIEL, gateway=gateway(model))
    view = await reports.load_report_view(session, report)

    # Findings come from code, in review order, each with evidence (rule 2).
    assert [f.title[:30] for f in view.findings][:2] == [
        "Documented assets of 9,226.32 ",
        "Incomplete: page 3 of the Augu",
    ]
    assert all(f.evidence for f in view.findings)
    # The Critic's code checks sent the draft back once; the second draft is used.
    assert model.count("UnderwritingDraft") == 2 and model.count("CriticVerdict") == 1
    assert [a.agent for a in view.agent_runs] == [
        AgentName.RESEARCHER,
        AgentName.WRITER,
        AgentName.CRITIC,
        AgentName.WRITER,
    ]
    assert report.guardrail_results["critic_returned_draft"] is True
    assert [c.text for c in view.conditions] == ["Provide the source of the large transfer."]
    sections = report.sections
    assert sections["snapshot"]["dti"] == "44.70%"
    assert sections["conflicts"][0]["evidence"][0] == {"type": "calculation", "name": "dti"}
    assert sections["guideline_references"]  # the Researcher's passages
    assert report.source.value == "agents"


async def test_whatever_still_fails_is_removed(session: AsyncSession) -> None:
    await stored_assets(session)
    model = RoutingModel([BAD_DRAFT])  # the Writer repeats its mistakes

    report = await run_underwriting(session, DANIEL, gateway=gateway(model))

    removed = {r["where"]: r["reason"] for r in report.guardrail_results["removed"]}
    assert removed == {
        "potential_risks[0]": "unverified figure",
        "conditions[1]": "decision wording",
    }
    assert report.sections["potential_risks"] == []
    text = json.dumps(report.sections).lower()
    assert "eligible" not in text and "12,345.67" not in text


async def test_a_failed_writer_still_completes_the_report(session: AsyncSession) -> None:
    await stored_assets(session)

    class Broken(RoutingModel):
        async def complete(self, request: AdapterRequest) -> AdapterResponse:
            if request.output_model.__name__ == "UnderwritingDraft":
                raise RuntimeError("down")
            return await super().complete(request)

    report = await run_underwriting(session, DANIEL, gateway=gateway(Broken([GOOD_DRAFT])))
    view = await reports.load_report_view(session, report)

    assert report.sections["potential_risks"] == ["not available"]
    assert view.findings  # the code-built findings are still there
    assert any(a.agent == AgentName.WRITER and a.status.value == "failed" for a in view.agent_runs)


async def test_rerunning_the_critic_writes_the_next_version(session: AsyncSession) -> None:
    await stored_assets(session)
    model = RoutingModel([GOOD_DRAFT])
    first = await run_underwriting(session, DANIEL, gateway=gateway(model))
    run = await session.get(reports.AnalysisRun, first.run_id)

    second = await run_underwriting(
        session, DANIEL, run=run, rerun=AgentName.CRITIC, gateway=gateway(model)
    )

    assert (second.run_id, second.version) == (first.run_id, 2)
    assert model.count("UnderwritingDraft") == 1  # the Writer was not run again


async def test_lm_agents_explain_the_rules_and_cite_regulation_x(session: AsyncSession) -> None:
    await seed_hardship_profile(session, ANGELA)
    await seed_loan_record(session, ANGELA, DATA["loan_record"])
    run = await run_recommendation_rules(session, ANGELA)
    draft = {
        "lender_view": "Foreclosure is a loss of 16,310.00 under illustrative settings.",
        "borrower_situation": "Hours were cut and the duration is unknown.",
        "missing_information": ["The August 2026 bank statement."],
        "compliance_points": ["12 CFR 1024.41(b): check the date the application was received."],
        "items_for_human_review": ["Confirm the hardship duration."],
    }
    model = RoutingModel([draft])

    report = await run_lm_agents(session, run, gateway=gateway(model))

    assert report.kind == ReportKind.LM_RECOMMENDATION and report.run_id == run.id
    refs = [r["passage_id"] for r in report.sections["guideline_references"]]
    assert any(r.startswith("sample-investor-a-v1.") for r in refs)  # the rules' passages
    assert any(r.startswith("reg-x-1024-41.") for r in refs)  # the Researcher's
    assert report.sections["facts_to_check"] == ["The date the application was received"]
    regulation_questions = [
        r
        for r in model.requests
        if r.output_model.__name__ == "GuidelineAnswerResult" and "Case " in r.messages[0].content
    ]
    assert regulation_questions  # the case facts went with the Regulation X questions


async def test_the_api_starts_the_agents_and_reruns_need_a_report(
    client: httpx.AsyncClient, session: AsyncSession, fake_queue: FakeQueue
) -> None:
    from app.main import app
    from app.services.queue import get_queue

    app.dependency_overrides[get_queue] = lambda: fake_queue
    try:
        uw = auth_headers(Role.UNDERWRITER)
        missing = await client.post(
            f"/api/v1/cases/{DANIEL}/underwriting-report/latest/agents/critic/rerun", headers=uw
        )
        assert missing.status_code in (202, 404)  # 202 when the seed already wrote a report
        started = await client.post(f"/api/v1/cases/{DANIEL}/underwriting-report", headers=uw)
        assert started.status_code == 202, started.text
        assert fake_queue.calls[-1][0] == "run_agents"
        bad = await client.post(
            f"/api/v1/cases/{DANIEL}/underwriting-report/latest/agents/judge/rerun", headers=uw
        )
        assert bad.status_code == 422
    finally:
        app.dependency_overrides.pop(get_queue, None)


async def test_the_worker_job_runs_the_agents(
    session: AsyncSession, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    await stored_assets(session)
    job = Job(kind="underwriting_agents", case_id=DANIEL, status=JobStatus.QUEUED)
    session.add(job)
    await session.commit()

    await run_agents_job(
        session_factory,
        job.id,
        None,
        "underwriting",
        None,
        gateway=gateway(RoutingModel([GOOD_DRAFT])),
    )

    await session.refresh(job)
    assert job.status == JobStatus.SUCCEEDED
    assert await session.scalar(sa.select(sa.func.count(AgentRun.id))) >= 3

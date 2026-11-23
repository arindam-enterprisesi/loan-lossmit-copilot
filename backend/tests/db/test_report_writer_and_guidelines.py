"""The report writer the agents' graph will call, and the read-only guideline endpoints.

A report written through ``report_writer`` must read back through the same endpoints as the seeded
sample; a finding with no evidence must be refused (rule 2); a re-run is a new version, never an
edit (rule 6). Every passage a seeded waterfall condition cites must open (rule 2).
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import httpx
import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.demo.reports import seed_lm_recommendation
from app.db.enums import (
    AgentName,
    AgentRunStatus,
    AnalysisFeature,
    ReportKind,
    ReviewPriority,
    Role,
)
from app.db.models import AnalysisRun
from app.db.seed import case_id, seed
from app.services import report_writer, reports
from app.services.guidelines import SeededPassageStore
from app.services.report_writer import (
    ConditionDraft,
    FindingDraft,
    MissingEvidenceError,
    ReportDraft,
)
from tests.db.conftest import auth_headers

DANIEL = case_id("Daniel Reyes — purchase")
ANGELA = case_id("Angela Whitfield — hardship")
BLOCKED = re.compile(r"\b(approve[sd]?|deny|denied|offer(s|ed)?|eligible|qualifies)\b", re.I)
DEMO = Path(__file__).resolve().parents[2] / "app" / "db" / "demo"


@pytest.fixture(autouse=True)
async def seeded(session: AsyncSession) -> None:
    await seed(session, "demo-pass")


def headers(role: Role = Role.UNDERWRITER) -> dict[str, str]:
    return auth_headers(role)


# --- the guideline endpoints -----------------------------------------------------------------


async def test_the_sources_are_listed_with_their_passage_counts(client: httpx.AsyncClient) -> None:
    response = await client.get("/api/v1/guidelines/sources", headers=headers())

    assert response.status_code == 200
    items = {s["id"]: s for s in response.json()["items"]}
    assert items["sample-investor-a-v1"]["passage_count"] == 10
    assert items["sample-investor-a-v1"]["label"] == "illustrative"
    assert items["reg-x-1024-41"]["kind"] == "regulation"


async def test_a_passage_opens_by_its_id_and_says_it_is_a_sample(client: httpx.AsyncClient) -> None:
    response = await client.get(
        "/api/v1/guidelines/passages/sample-investor-a-v1.loan-modification.3", headers=headers()
    )

    assert response.status_code == 200
    passage = response.json()
    assert passage["heading"] == "Loan modification: target payment"
    assert "35% of the borrower's documented gross monthly income" in passage["text"]
    assert passage["source_title"].startswith("Sample Investor A")
    assert passage["label"] == "illustrative" and passage["notice"].startswith("Seeded sample")


async def test_an_unknown_passage_is_a_404_and_a_token_is_needed(client: httpx.AsyncClient) -> None:
    missing = await client.get("/api/v1/guidelines/passages/nope.1", headers=headers())

    assert (missing.status_code, missing.json()["code"]) == (404, "not_found")
    assert (await client.get("/api/v1/guidelines/sources")).status_code == 401
    assert (await client.get("/api/v1/guidelines/passages/x")).status_code == 401


@pytest.mark.parametrize("role", [Role.UNDERWRITER, Role.LM_SPECIALIST, Role.ADMIN])
async def test_every_role_may_read_the_guidelines(client: httpx.AsyncClient, role: Role) -> None:
    for path in ("sources", "passages/reg-x-1024-41.b"):
        assert (
            await client.get(f"/api/v1/guidelines/{path}", headers=headers(role))
        ).status_code == 200


async def test_there_is_no_way_to_write_a_passage(client: httpx.AsyncClient) -> None:
    for method in ("post", "put", "patch", "delete"):
        response = await client.request(
            method, "/api/v1/guidelines/sources", json={}, headers=headers(Role.ADMIN)
        )
        assert response.status_code == 405


def test_every_passage_the_seeded_waterfall_cites_opens() -> None:
    store = SeededPassageStore()
    options = json.loads((DEMO / "angela_lm_recommendation.json").read_text(encoding="utf-8"))
    cited = {c["passage_id"] for o in options["options"] for c in o["conditions"]}

    assert cited and all(store.passage(p) is not None for p in cited)


def test_the_seeded_passages_carry_no_decision_wording_and_unique_ids() -> None:
    data = json.loads((DEMO / "guideline_passages.json").read_text(encoding="utf-8"))
    store = SeededPassageStore()

    assert len(store.passage_ids()) == len(data["passages"]) == 11
    texts = [p["text"] + " " + p["heading"] for p in data["passages"]]
    assert not [t for t in texts if BLOCKED.search(t)]


def test_a_passage_with_an_unknown_source_is_refused(tmp_path: Path) -> None:
    bad = tmp_path / "p.json"
    bad.write_text(
        json.dumps(
            {
                "sources": [{"id": "a", "title": "A", "kind": "k", "label": "illustrative"}],
                "passages": [{"id": "a.1", "source_id": "zzz", "heading": "h", "text": "t"}],
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="unknown sources"):
        SeededPassageStore(bad)


# --- the report writer -----------------------------------------------------------------------


def draft(*, evidence: list[dict[str, Any]] | None = None, title: str = "A finding") -> ReportDraft:
    return ReportDraft(
        sections={"snapshot": {"borrower": "Daniel Reyes"}},
        findings=[
            FindingDraft(
                ReviewPriority.SIGNIFICANT,
                title,
                "Detail.",
                [{"type": "calculation", "name": "dti"}] if evidence is None else evidence,
            )
        ],
        conditions=[
            ConditionDraft("Provide the gift letter.", ReviewPriority.SIGNIFICANT),
            ConditionDraft("Provide page 3.", ReviewPriority.ATTENTION),
        ],
        guardrail_results={"critic": "passed"},
    )


async def test_a_report_the_agents_write_reads_back_like_the_seeded_one(
    client: httpx.AsyncClient, session: AsyncSession
) -> None:
    run = await report_writer.start_run(session, DANIEL, AnalysisFeature.UNDERWRITING)
    await report_writer.write_report(session, run, ReportKind.UNDERWRITING, draft())
    await report_writer.record_agent_run(
        session,
        run,
        AgentName.RESEARCHER,
        status=AgentRunStatus.SUCCEEDED,
        provider="bedrock",
        model="haiku",
        prompt_id="researcher@1",
        output={"passages": 2},
    )
    await report_writer.finish_run(session, run)

    response = await client.get(
        f"/api/v1/cases/{DANIEL}/underwriting-report/latest", headers=headers()
    )

    view = response.json()
    assert (view["report"]["source"], view["report"]["notice"]) == ("agents", None)
    assert (view["report"]["status"], view["report"]["version"]) == ("draft", 1)
    assert view["run_status"] == "succeeded"
    assert [c["text"] for c in view["conditions"]] == [
        "Provide the gift letter.",
        "Provide page 3.",
    ]
    assert [c["position"] for c in view["conditions"]] == [1, 2]
    assert view["findings"][0]["evidence"] == [{"type": "calculation", "name": "dti"}]
    assert view["report"]["guardrail_results"] == {"critic": "passed"}
    [agent] = view["agent_runs"]
    assert (agent["agent"], agent["provider"], agent["prompt_id"]) == (
        "researcher",
        "bedrock",
        "researcher@1",
    )


async def test_a_finding_with_no_evidence_is_refused_and_nothing_is_stored(
    session: AsyncSession,
) -> None:
    run = await report_writer.start_run(session, DANIEL, AnalysisFeature.UNDERWRITING)

    with pytest.raises(MissingEvidenceError):
        await report_writer.write_report(session, run, ReportKind.UNDERWRITING, draft(evidence=[]))

    assert await reports.latest_report(session, DANIEL, ReportKind.UNDERWRITING) is None


async def test_a_rerun_is_a_new_version_and_the_newest_is_the_one_reviewed(
    client: httpx.AsyncClient, session: AsyncSession
) -> None:
    run = await report_writer.start_run(session, DANIEL, AnalysisFeature.UNDERWRITING)
    first = await report_writer.write_report(session, run, ReportKind.UNDERWRITING, draft())
    second = await report_writer.write_report(
        session, run, ReportKind.UNDERWRITING, draft(title="A finding, rewritten")
    )
    url = f"/api/v1/cases/{DANIEL}/underwriting-report/latest"

    assert (first.version, second.version) == (1, 2)
    view = (await client.get(url, headers=headers())).json()
    assert view["report"]["version"] == 2 and view["findings"][0]["title"] == "A finding, rewritten"
    old_condition = (
        await session.execute(
            sa.text("SELECT id FROM conditions WHERE report_id = :r LIMIT 1"),
            {"r": first.id},
        )
    ).scalar_one()
    stale = await client.patch(
        f"{url.replace('/latest', '')}/latest/conditions/{old_condition}",
        json={"decision": "accepted"},
        headers=headers(),
    )
    assert stale.status_code == 409
    # A sign-off names the version it reviewed, so the same person can review version 2.
    signed = await client.post(
        f"{url.replace('/latest', '')}/latest/sign-off", json={}, headers=headers()
    )
    assert signed.json()["sign_off"]["report_version"] == 2


async def test_each_attempt_of_an_agent_is_numbered_in_order(session: AsyncSession) -> None:
    run = await report_writer.start_run(session, DANIEL, AnalysisFeature.UNDERWRITING)

    attempts = [
        (
            await report_writer.record_agent_run(
                session,
                run,
                AgentName.WRITER,
                status=AgentRunStatus.FAILED if n == 0 else AgentRunStatus.SUCCEEDED,
            )
        ).attempt
        for n in range(3)
    ]
    other = await report_writer.record_agent_run(
        session, run, AgentName.CRITIC, status=AgentRunStatus.SUCCEEDED
    )

    assert attempts == [1, 2, 3] and other.attempt == 1


async def test_a_waterfall_report_the_graph_adds_later_is_read_with_the_waterfall(
    client: httpx.AsyncClient, session: AsyncSession
) -> None:
    seeded_report = await seed_lm_recommendation(session, ANGELA)
    run = await session.get(AnalysisRun, seeded_report.run_id)
    assert run is not None

    await report_writer.write_report(
        session,
        run,
        ReportKind.LM_RECOMMENDATION,
        ReportDraft(sections={"lender_view": "Rewritten."}),
    )

    view = (
        await client.get(
            f"/api/v1/cases/{ANGELA}/lm-recommendation/latest", headers=headers(Role.LM_SPECIALIST)
        )
    ).json()
    assert view["report"]["report"]["version"] == 2
    assert view["report"]["report"]["sections"]["lender_view"] == "Rewritten."

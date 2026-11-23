"""Seed the two reports the review screens start from, without calling a model.

Until the agents run (D7 and D8), the demo needs something to review: a draft underwriting report
for Daniel Reyes (the Feature Design 6.8 worked example, with its six suggested conditions) and a
waterfall, lender view and draft report for Angela Whitfield (the 8.8 worked example). They are data
files, written by hand and labelled ``seeded_sample`` everywhere (the report, its agent runs and the
run itself), so nobody mistakes them for an agent's or the rules engine's output. The review
endpoints work the same on them as on real output. The waterfall is replaced by the real rules
engine on D7, and the reports by the agents' own on D8.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.enums import (
    AgentName,
    AgentRunStatus,
    AnalysisFeature,
    AnalysisStatus,
    ReportKind,
    ReportSource,
    ReviewPriority,
    WaterfallOption,
    WaterfallStatus,
)
from app.db.models import (
    AnalysisRun,
    Calculation,
    LenderView,
    Report,
    WaterfallResult,
)
from app.services import report_writer
from app.services.report_writer import ConditionDraft, FindingDraft, ReportDraft
from app.services.waterfall_status import recompute

UNDERWRITING_FILE = Path(__file__).with_name("daniel_underwriting_report.json")
LM_FILE = Path(__file__).with_name("angela_lm_recommendation.json")
SEED_PROVIDER = "seeded_sample"


def _load(path: Path) -> dict[str, Any]:
    data: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return data


async def _seeded_report(
    session: AsyncSession, case_id: uuid.UUID, kind: ReportKind
) -> Report | None:
    return await session.scalar(
        sa.select(Report).where(
            Report.case_id == case_id,
            Report.kind == kind,
            Report.source == ReportSource.SEEDED_SAMPLE,
        )
    )


async def _run(
    session: AsyncSession,
    case_id: uuid.UUID,
    feature: AnalysisFeature,
    config_versions: dict[str, Any],
) -> AnalysisRun:
    run = await report_writer.start_run(
        session, case_id, feature, config_versions=config_versions, status=AnalysisStatus.SUCCEEDED
    )
    await report_writer.finish_run(session, run)
    return run


async def _agent_runs(
    session: AsyncSession, run: AnalysisRun, agents: list[dict[str, str]]
) -> None:
    now = datetime.now(UTC)
    for entry in agents:
        await report_writer.record_agent_run(
            session,
            run,
            AgentName(entry["agent"]),
            status=AgentRunStatus.SUCCEEDED,
            provider=SEED_PROVIDER,
            output={"summary": entry["summary"], "seeded": True},
            started_at=now,
            finished_at=now,
        )


async def seed_underwriting_report(session: AsyncSession, case_id: uuid.UUID) -> Report:
    """A draft underwriting report with findings and six suggested conditions, unless the case
    already has a seeded one. The caller commits."""
    existing = await _seeded_report(session, case_id, ReportKind.UNDERWRITING)
    if existing is not None:
        return existing
    data = _load(UNDERWRITING_FILE)
    run = await _run(session, case_id, AnalysisFeature.UNDERWRITING, {})
    report = await report_writer.write_report(
        session,
        run,
        ReportKind.UNDERWRITING,
        ReportDraft(
            sections={**data["sections"], "label": data["label"]},
            findings=[
                FindingDraft(ReviewPriority(f["priority"]), f["title"], f["detail"], f["evidence"])
                for f in data["findings"]
            ],
            conditions=[
                ConditionDraft(c["text"], ReviewPriority(c["priority"])) for c in data["conditions"]
            ],
            guardrail_results={"seeded": True, "checked": "not run: hand-written sample"},
        ),
        source=ReportSource.SEEDED_SAMPLE,
    )
    await _agent_runs(session, run, data["agents"])
    return report


def seeded_statuses(options: list[dict[str, Any]]) -> list[tuple[str, list[dict[str, Any]]]]:
    """The statuses the rules would give the seeded conditions, for the test that keeps the file
    consistent with ``waterfall_status``."""
    return recompute([o["conditions"] for o in options])


async def seed_lm_recommendation(session: AsyncSession, case_id: uuid.UUID) -> Report:
    """A waterfall, lender view and draft report for the loss mitigation case, unless it already
    has a seeded one. The caller commits."""
    existing = await _seeded_report(session, case_id, ReportKind.LM_RECOMMENDATION)
    if existing is not None:
        return existing
    data = _load(LM_FILE)
    rule_set = data["rule_set"]
    run = await _run(
        session,
        case_id,
        AnalysisFeature.LM_RECOMMENDATION,
        {"rule_set": {**rule_set, "hash": ""}},
    )
    for number, option in enumerate(data["options"], start=1):
        status = WaterfallStatus(option["status"])
        session.add(
            WaterfallResult(
                run_id=run.id,
                rule_set_version=rule_set["version"],
                order_no=number,
                option=WaterfallOption(option["option"]),
                status=status,
                original_status=status,
                conditions=option["conditions"],
            )
        )
    ids: list[uuid.UUID] = []
    for figure in data["lender_view"]["figures"]:
        calc = Calculation(
            run_id=run.id,
            case_id=case_id,
            name=figure["name"],
            value=Decimal(figure["value"]),
            unit=figure["unit"],
            formula=figure["formula"],
            inputs={"source": "seeded sample"},
            working=figure["working"],
            evidence=[{"source": "rule set lender view settings"}, {"source": "loan record"}],
        )
        session.add(calc)
        await session.flush()
        ids.append(calc.id)
    figures = {f["name"]: Decimal(f["value"]) for f in data["lender_view"]["figures"]}
    session.add(
        LenderView(
            run_id=run.id,
            foreclosure_loss=figures["foreclosure_loss"],
            modification_cost=figures["modification_cost"],
            advantage=figures["modification_advantage"],
            settings=data["lender_view"]["settings"],
            calculation_ids=ids,
        )
    )
    report = await report_writer.write_report(
        session,
        run,
        ReportKind.LM_RECOMMENDATION,
        ReportDraft(
            sections={**data["report_sections"], "label": data["label"]},
            guardrail_results={"seeded": True, "checked": "not run: hand-written sample"},
        ),
        source=ReportSource.SEEDED_SAMPLE,
    )
    await _agent_runs(session, run, data["agents"])
    return report

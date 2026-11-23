"""The one way a report gets into the database: for the agents' graph (D7 and D8) and the seeds.

Arindam's graph calls these functions with what the agents produced; they store it as a draft with
its findings, suggested conditions and the run log of each agent, and ``services.reports`` reads it
back for the API. Nothing is decided here: a report is a draft until a person reviews it
(``review_conditions``). Two things are enforced on the way in, so no caller can skip them:

* every finding carries evidence (rule 2): a document line, a calculation, a rule or a passage;
* a new version of a report (an agent re-run) is a new row, never an edit of the old one (rule 6).
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.enums import (
    AgentName,
    AgentRunStatus,
    AnalysisFeature,
    AnalysisStatus,
    ConditionSource,
    ReportKind,
    ReportSource,
    ReviewPriority,
)
from app.db.models import AgentRun, AnalysisRun, Condition, Finding, Report


@dataclass(frozen=True)
class FindingDraft:
    priority: ReviewPriority
    title: str
    detail: str
    evidence: Sequence[dict[str, Any]]
    flag_id: uuid.UUID | None = None


@dataclass(frozen=True)
class ConditionDraft:
    text: str
    priority: ReviewPriority


@dataclass(frozen=True)
class ReportDraft:
    sections: dict[str, Any]
    findings: Sequence[FindingDraft] = ()
    conditions: Sequence[ConditionDraft] = ()
    guardrail_results: dict[str, Any] = field(default_factory=dict)


class MissingEvidenceError(ValueError):
    """A finding with nothing to point at: rule 2 says every finding links to evidence."""


async def start_run(
    session: AsyncSession,
    case_id: uuid.UUID,
    feature: AnalysisFeature,
    *,
    created_by: uuid.UUID | None = None,
    config_versions: dict[str, Any] | None = None,
    status: AnalysisStatus = AnalysisStatus.RUNNING,
    job_id: uuid.UUID | None = None,
) -> AnalysisRun:
    run = AnalysisRun(
        case_id=case_id,
        feature=feature,
        status=status,
        job_id=job_id,
        created_by=created_by,
        config_versions=config_versions or {},
        started_at=datetime.now(UTC),  # set here, not by now(): runs in one transaction must order
    )
    session.add(run)
    await session.flush()
    return run


async def finish_run(
    session: AsyncSession, run: AnalysisRun, status: AnalysisStatus = AnalysisStatus.SUCCEEDED
) -> None:
    run.status, run.finished_at = status, datetime.now(UTC)
    await session.flush()


async def write_report(
    session: AsyncSession,
    run: AnalysisRun,
    kind: ReportKind,
    draft: ReportDraft,
    *,
    source: ReportSource = ReportSource.AGENTS,
) -> Report:
    """Store a draft report as the next version of this run's report."""
    for finding in draft.findings:
        if not finding.evidence:
            raise MissingEvidenceError(f"finding {finding.title!r} has no evidence")
    last = await session.scalar(
        sa.select(sa.func.max(Report.version)).where(Report.run_id == run.id)
    )
    report = Report(
        run_id=run.id,
        case_id=run.case_id,
        kind=kind,
        version=(last or 0) + 1,
        sections=draft.sections,
        guardrail_results=draft.guardrail_results,
        source=source,
    )
    session.add(report)
    await session.flush()
    for finding in draft.findings:
        session.add(
            Finding(
                report_id=report.id,
                priority=finding.priority,
                title=finding.title,
                detail=finding.detail,
                evidence=list(finding.evidence),
                flag_id=finding.flag_id,
            )
        )
    for position, condition in enumerate(draft.conditions, start=1):
        session.add(
            Condition(
                report_id=report.id,
                position=position,
                text=condition.text,
                priority=condition.priority,
                source=ConditionSource.AGENT,
            )
        )
    await session.flush()
    return report


async def record_agent_run(
    session: AsyncSession,
    run: AnalysisRun,
    agent: AgentName,
    *,
    status: AgentRunStatus,
    provider: str | None = None,
    model: str | None = None,
    prompt_id: str | None = None,
    output: dict[str, Any] | None = None,
    error: str | None = None,
    started_at: datetime | None = None,
    finished_at: datetime | None = None,
) -> AgentRun:
    """Add one attempt of an agent to the run log. The attempt number follows the earlier ones."""
    last = await session.scalar(
        sa.select(sa.func.max(AgentRun.attempt)).where(
            AgentRun.run_id == run.id, AgentRun.agent == agent
        )
    )
    row = AgentRun(
        run_id=run.id,
        agent=agent,
        attempt=(last or 0) + 1,
        status=status,
        provider=provider,
        model=model,
        prompt_id=prompt_id,
        output=output,
        error=error,
        started_at=started_at,
        finished_at=finished_at,
    )
    session.add(row)
    await session.flush()
    return row

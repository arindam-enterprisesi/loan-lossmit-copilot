"""Reading a case's newest report, with its findings, conditions, agent runs and sign-offs.

The agents (Arindam's graph, D7 and D8) write into these tables; the seeded samples in
``app/db/demo`` fill them until then. This module only reads: the review actions are in
``review_conditions``. A run is never edited into something else, so "latest" is the newest run's
newest report version.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.enums import ReportKind
from app.db.models import (
    AgentRun,
    AnalysisRun,
    Calculation,
    Condition,
    Finding,
    LenderView,
    Report,
    SignOff,
    WaterfallResult,
)


@dataclass
class ReportView:
    run: AnalysisRun
    report: Report
    findings: list[Finding]
    conditions: list[Condition]
    agent_runs: list[AgentRun]
    sign_offs: list[SignOff]


@dataclass
class WaterfallView:
    run: AnalysisRun
    options: list[WaterfallResult]
    lender_view: LenderView | None
    calculations: dict[uuid.UUID, Calculation]
    report: ReportView | None


async def latest_report(
    session: AsyncSession, case_id: uuid.UUID, kind: ReportKind
) -> Report | None:
    """The newest report of the kind: the newest run's highest version."""
    return await session.scalar(
        sa.select(Report)
        .join(AnalysisRun, AnalysisRun.id == Report.run_id)
        .where(Report.case_id == case_id, Report.kind == kind)
        .order_by(AnalysisRun.started_at.desc(), Report.version.desc(), Report.id)
        .limit(1)
    )


async def load_report_view(session: AsyncSession, report: Report) -> ReportView:
    run = await session.get(AnalysisRun, report.run_id)
    assert run is not None  # the foreign key guarantees it
    findings = (
        (
            await session.execute(
                sa.select(Finding)
                .where(Finding.report_id == report.id)
                .order_by(
                    sa.case(
                        (Finding.priority == "significant", 0),
                        (Finding.priority == "attention", 1),
                        else_=2,
                    ),
                    Finding.created_at,
                    Finding.id,
                )
            )
        )
        .scalars()
        .all()
    )
    conditions = (
        (
            await session.execute(
                sa.select(Condition)
                .where(Condition.report_id == report.id)
                .order_by(Condition.position, Condition.created_at, Condition.id)
            )
        )
        .scalars()
        .all()
    )
    agents = (
        (
            await session.execute(
                sa.select(AgentRun)
                .where(AgentRun.run_id == report.run_id)
                .order_by(
                    AgentRun.attempt,
                    # The workflow's order, not the alphabet's (rows made together share a time).
                    sa.case(
                        (AgentRun.agent == "researcher", 0),
                        (AgentRun.agent == "writer", 1),
                        else_=2,
                    ),
                    AgentRun.created_at,
                )
            )
        )
        .scalars()
        .all()
    )
    sign_offs = (
        (
            await session.execute(
                sa.select(SignOff)
                .where(SignOff.report_id == report.id)
                .order_by(SignOff.signed_at, SignOff.id)
            )
        )
        .scalars()
        .all()
    )
    return ReportView(run, report, list(findings), list(conditions), list(agents), list(sign_offs))


async def latest_waterfall_run(session: AsyncSession, case_id: uuid.UUID) -> AnalysisRun | None:
    return await session.scalar(
        sa.select(AnalysisRun)
        .where(AnalysisRun.case_id == case_id, AnalysisRun.feature == "lm_recommendation")
        .order_by(AnalysisRun.started_at.desc(), AnalysisRun.id.desc())
        .limit(1)
    )


async def load_waterfall_view(session: AsyncSession, run: AnalysisRun) -> WaterfallView:
    options = (
        (
            await session.execute(
                sa.select(WaterfallResult)
                .where(WaterfallResult.run_id == run.id)
                .order_by(WaterfallResult.order_no)
            )
        )
        .scalars()
        .all()
    )
    lender = await session.scalar(sa.select(LenderView).where(LenderView.run_id == run.id))
    wanted = list(lender.calculation_ids) if lender else []
    calcs = {}
    if wanted:
        rows = (
            (await session.execute(sa.select(Calculation).where(Calculation.id.in_(wanted))))
            .scalars()
            .all()
        )
        calcs = {c.id: c for c in rows}
    report = await session.scalar(
        sa.select(Report).where(Report.run_id == run.id).order_by(Report.version.desc()).limit(1)
    )
    return WaterfallView(
        run=run,
        options=list(options),
        lender_view=lender,
        calculations=calcs,
        report=await load_report_view(session, report) if report else None,
    )

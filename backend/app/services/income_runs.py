"""Income analysis runs: start one, run it in the worker, store it, read it, change a component.

``app.services.income`` does the analysis (pure). This module is the database side:

* ``start_run`` records the request (a run and a job) and queues it;
* ``run_income_job`` is what the worker runs: load the case's documents, analyse, store the figures,
  components and flags, and finish the job;
* ``load_view`` reads a stored run back;
* ``set_component_included`` is a person including or excluding a component, with a reason. It
  recalculates the candidate at once, with no model call, keeps what the system decided beside the
  person's change, and writes an audit event.

A run is never edited into something else (rule 6): a new request is a new run, and the previous
ones stay as history.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.enums import (
    AnalysisFeature,
    AnalysisStatus,
    IncomeComponentKind,
    JobStatus,
)
from app.db.models import AnalysisRun, Calculation, Flag, IncomeComponent, Job
from app.services import audit
from app.services import flags as flag_service
from app.services.analysis_config import AnalysisConfig, get_analysis_config
from app.services.calculations import candidate_total, cents, money
from app.services.case_facts import load_case_documents
from app.services.config_versions import record_config_versions
from app.services.documents import UploadFailedError
from app.services.income import KIND_LABELS, IncomeOutcome, analyze, flag_entity_id
from app.services.pipeline import cause_chain
from app.services.queue import INCOME_FUNCTION, JobQueue
from app.services.security import CurrentUser
from app.settings import get_settings

logger = logging.getLogger(__name__)

INCOME_JOB_KIND = "income_analysis"
CANDIDATE = "candidate_monthly_income"
FAILED_MESSAGE = "The income analysis could not be completed."
KIND_ORDER = [kind.value for kind in IncomeComponentKind]


class IncomeError(Exception):
    """A request the analysis cannot honour. ``status`` and ``code`` are for the API."""

    def __init__(self, status: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status, self.code, self.message = status, code, message


def _now() -> datetime:
    return datetime.now(UTC)


# --- starting a run -------------------------------------------------------------------------


async def start_run(
    session: AsyncSession, queue: JobQueue, user: CurrentUser, case_id: uuid.UUID
) -> tuple[AnalysisRun, Job]:
    """Record the request, then queue it. Commits, because the job is queued only after the rows."""
    job = Job(kind=INCOME_JOB_KIND, case_id=case_id, status=JobStatus.QUEUED)
    session.add(job)
    await session.flush()
    run = AnalysisRun(
        case_id=case_id,
        feature=AnalysisFeature.INCOME,
        status=AnalysisStatus.QUEUED,
        job_id=job.id,
        started_at=_now(),  # set here, not by now(): runs made in one transaction must still order
        created_by=uuid.UUID(user.id),
    )
    session.add(run)
    await session.flush()
    await audit.record(
        session,
        actor_id=uuid.UUID(user.id),
        role=user.role.value,
        action="income.run_requested",
        entity_type="analysis_run",
        entity_id=run.id,
        case_id=case_id,
        after={"job_id": str(job.id)},
    )
    await session.commit()
    try:
        await queue.enqueue(INCOME_FUNCTION, str(job.id), str(run.id), job_id=str(job.id))
    except Exception as exc:
        logger.warning("queueing job %s failed: %s", job.id, type(exc).__name__)
        job.status = JobStatus.FAILED
        job.error = "The analysis was saved but could not be queued."
        run.status = AnalysisStatus.FAILED
        run.finished_at = _now()
        await session.commit()
        raise UploadFailedError(
            "queue_unavailable", "The analysis was saved but could not be queued. Please try again."
        ) from exc
    await session.refresh(job)
    await session.refresh(run)
    return run, job


# --- the worker -----------------------------------------------------------------------------


async def persist(
    session: AsyncSession, run: AnalysisRun, outcome: IncomeOutcome, cfg: AnalysisConfig
) -> None:
    """Store an analysis. Safe to run again for the same run: it replaces what was stored."""
    uses = cfg.uses()
    await record_config_versions(session, uses)
    run.config_versions = cfg.snapshot(uses)

    await session.execute(sa.delete(IncomeComponent).where(IncomeComponent.run_id == run.id))
    await session.execute(sa.delete(Calculation).where(Calculation.run_id == run.id))
    await session.execute(
        sa.delete(Flag).where(
            Flag.feature == "income", Flag.evidence["run_id"].astext == str(run.id)
        )
    )
    calc_ids: dict[int, uuid.UUID] = {}
    for calc in outcome.calcs:
        row = Calculation(
            run_id=run.id,
            case_id=run.case_id,
            name=calc.name,
            value=calc.value,
            unit=calc.unit,
            formula=calc.formula,
            inputs=dict(calc.inputs),
            working=calc.working,
            evidence=list(calc.evidence) or None,
        )
        session.add(row)
        await session.flush()
        calc_ids[id(calc)] = row.id
    for part in outcome.components:
        session.add(
            IncomeComponent(
                run_id=run.id,
                borrower=part.borrower,
                employer=part.employer,
                component=IncomeComponentKind(part.kind),
                current_period=part.current_period,
                ytd=part.ytd,
                monthly=part.monthly,
                included=part.included,
                exclusion_reason=part.exclusion_reason,
                original_included=part.included,
                original_exclusion_reason=part.exclusion_reason,
                calculation_id=calc_ids.get(id(part.calc)),
            )
        )
    for found in outcome.flags:
        await flag_service.raise_flag(
            session,
            case_id=run.case_id,
            entity_type="income_check",
            entity_id=flag_entity_id(run.id, found.code, found.key),
            code=found.code,
            severity=found.severity,
            message=found.message,
            evidence={
                "run_id": str(run.id),
                "check": found.key,
                "refs": list(found.evidence),
                "working": found.working,
            },
            feature="income",
        )
    await session.flush()


async def run_income_job(
    factory: async_sessionmaker[AsyncSession],
    job_id: uuid.UUID,
    run_id: uuid.UUID,
    *,
    config: AnalysisConfig | None = None,
) -> None:
    """What the worker runs: analyse the case's documents and store the result."""
    cfg = config or get_analysis_config()
    async with factory() as session:
        job, run = await session.get(Job, job_id), await session.get(AnalysisRun, run_id)
        if job is None or run is None:
            raise LookupError(f"income job {job_id} or run {run_id} does not exist")
        job.status, job.stage, job.progress = JobStatus.RUNNING, "collect", 0.1
        job.attempts += 1
        run.status = AnalysisStatus.RUNNING
        await session.commit()
        try:
            documents = await load_case_documents(session, run.case_id)
            job.stage, job.progress = "calculate", 0.5
            await session.commit()
            outcome = analyze(documents, cfg)
            job.stage, job.progress = "save", 0.8
            await persist(session, run, outcome, cfg)
            job.stage, job.progress = "explain", 0.9
            explained = await explain_flags(session, run)
            run.status, run.finished_at = AnalysisStatus.SUCCEEDED, _now()
            job.status, job.stage, job.progress, job.error = JobStatus.SUCCEEDED, "done", 1.0, None
            await audit.record(
                session,
                actor_id=None,
                role="worker",
                action="income.analysed",
                entity_type="analysis_run",
                entity_id=run.id,
                case_id=run.case_id,
                after={
                    "candidate_monthly_income": str(outcome.candidate.value),
                    "components": len(outcome.components),
                    "flags": len(outcome.flags),
                    "explanations": explained,
                    "config_versions": run.config_versions,
                },
            )
            await session.commit()
        except Exception as exc:
            await session.rollback()
            logger.warning("income analysis failed run=%s: %s", run_id, cause_chain(exc))
            job, run = await session.get(Job, job_id), await session.get(AnalysisRun, run_id)
            if job is not None and run is not None:
                job.status, job.error = JobStatus.FAILED, FAILED_MESSAGE
                run.status, run.finished_at = AnalysisStatus.FAILED, _now()
                await session.commit()


# --- possible explanations of the flags (income-explain@1, Feature Design 2.5) ---------------


async def explain_flags(session: AsyncSession, run: AnalysisRun, *, gateway: Any = None) -> str:
    """Ask for possible explanations of the run's flags and keep each one on its flag.

    The model sees the stored flags and calculations only (never a document); code checks every
    figure it writes. Nothing here can fail the analysis: without a provider (``PIPELINE_LLM=fake``)
    or when the call fails, the flags simply have no explanation and the result says why.
    Returns what happened: "generated", "none needed", "skipped" or "failed".
    """
    if gateway is None and get_settings().pipeline_llm == "fake":
        return "skipped"
    view = await load_view(session, run)
    if not view.flags:
        return "none needed"
    try:
        from app.llm.income import StoredCalculation, StoredFlag, explain_stored_flags

        found = await explain_stored_flags(
            [StoredFlag(f.code, f.message, _working(f)) for f in view.flags],
            [StoredCalculation(c.name, c.formula, c.working) for c in view.ordered_calculations],
            gateway=gateway,
        )
    except Exception as exc:
        logger.warning("income explanations failed run=%s: %s", run.id, cause_chain(exc))
        return "failed"
    for flag in view.flags:
        if flag.code in found:
            # A new dict, so the JSONB column sees the change; the flag's own evidence is kept.
            flag.evidence = {**(flag.evidence or {}), "explanation": found[flag.code]}
    await session.flush()
    return "generated"


def _working(flag: Flag) -> str | None:
    working = (flag.evidence or {}).get("working")
    return str(working) if working else None


# --- reading a run --------------------------------------------------------------------------


@dataclass
class IncomeView:
    run: AnalysisRun
    components: list[IncomeComponent]
    calculations: dict[uuid.UUID, Calculation]
    ordered_calculations: list[Calculation]
    flags: list[Flag]
    candidate: Calculation | None

    def version_string(self) -> str:
        return version_string(self.run.config_versions)


def version_string(config_versions: dict[str, Any]) -> str:
    """``Calc.config_version`` for a run: ``"income_method@2026-11-19.1, thresholds@..."``."""
    return ", ".join(
        f"{kind}@{config_versions[kind]['version']}"
        for kind in ("income_method", "thresholds")
        if kind in config_versions
    )


async def latest_run(session: AsyncSession, case_id: uuid.UUID) -> AnalysisRun | None:
    """The newest income run of the case, in any state."""
    return await session.scalar(
        sa.select(AnalysisRun)
        .where(AnalysisRun.case_id == case_id, AnalysisRun.feature == AnalysisFeature.INCOME)
        .order_by(AnalysisRun.started_at.desc(), AnalysisRun.id.desc())
        .limit(1)
    )


async def load_view(session: AsyncSession, run: AnalysisRun) -> IncomeView:
    components = list(
        (await session.execute(sa.select(IncomeComponent).where(IncomeComponent.run_id == run.id)))
        .scalars()
        .all()
    )
    components.sort(
        key=lambda c: (c.borrower, c.employer or "", KIND_ORDER.index(c.component.value))
    )
    rows = list(
        (
            await session.execute(
                sa.select(Calculation)
                .where(Calculation.run_id == run.id)
                .order_by(Calculation.created_at, Calculation.name)
            )
        )
        .scalars()
        .all()
    )
    flags = list(
        (
            await session.execute(
                sa.select(Flag)
                .where(Flag.feature == "income", Flag.evidence["run_id"].astext == str(run.id))
                .order_by(Flag.code, Flag.id)
            )
        )
        .scalars()
        .all()
    )
    return IncomeView(
        run=run,
        components=components,
        calculations={c.id: c for c in rows},
        ordered_calculations=rows,
        flags=flags,
        candidate=next((c for c in rows if c.name == CANDIDATE), None),
    )


# --- a person includes or excludes a component ----------------------------------------------


async def set_component_included(
    session: AsyncSession,
    user: CurrentUser,
    case_id: uuid.UUID,
    component_id: uuid.UUID,
    *,
    included: bool,
    reason: str,
) -> IncomeView:
    """Include or exclude a component, with a reason. Recalculates at once; no model is called."""
    component = await session.get(IncomeComponent, component_id)
    run = await session.get(AnalysisRun, component.run_id) if component else None
    if component is None or run is None or run.case_id != case_id:
        raise IncomeError(404, "not_found", "Component not found")
    newest = await latest_run(session, case_id)
    if newest is None or newest.id != run.id:
        raise IncomeError(409, "stale_analysis", "A newer income analysis has replaced this one.")

    view = await load_view(session, run)
    before_total = view.candidate.value if view.candidate else None
    before = {
        "included": component.included,
        "exclusion_reason": component.exclusion_reason,
        "candidate_monthly_income": (
            str(cents(before_total)) if before_total is not None else None
        ),
    }
    component.included = included
    component.exclusion_reason = None if included else reason  # what is shown while it is out
    component.review_reason = reason  # the person's own, for including as well as excluding
    component.updated_by, component.updated_at = uuid.UUID(user.id), _now()
    await session.flush()

    version = version_string(run.config_versions)
    counted = [(KIND_LABELS[c.component.value], c.monthly) for c in view.components if c.included]
    total = candidate_total(counted, version=version)
    if view.candidate is not None:
        view.candidate.value = total.value
        view.candidate.inputs = dict(total.inputs)
        view.candidate.working = total.working
    await audit.record(
        session,
        actor_id=uuid.UUID(user.id),
        role=user.role.value,
        action="income.component_included" if included else "income.component_excluded",
        entity_type="income_component",
        entity_id=component.id,
        case_id=case_id,
        before=before,
        after={
            "included": included,
            "exclusion_reason": component.exclusion_reason,
            "candidate_monthly_income": str(total.value),
            "working": total.working,
            "component": KIND_LABELS[component.component.value],
            "monthly": money(component.monthly),
        },
        reason=reason,
    )
    await session.commit()
    return await load_view(session, run)

"""Running the agents in the worker: start a job from the API, run it, record the outcome.

    POST /cases/{id}/underwriting-report                          -> kind "underwriting"
    POST /cases/{id}/underwriting-report/latest/agents/{a}/rerun  -> kind "underwriting", agent a
    POST /cases/{id}/lm-recommendation/latest/agents/{a}/rerun    -> kind "lm", agent a

The LM agents also run straight after the rules in ``run_recommendation_job``
(``run_lm_after_rules``). A failed agent never fails the job: the report completes with the
section marked "not available" (Feature Design 6.5). Only an error outside the agents does.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any, Literal

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.enums import AgentName, JobStatus
from app.db.models import AnalysisRun, Job
from app.services import audit
from app.services.documents import UploadFailedError
from app.services.queue import JobQueue
from app.services.security import CurrentUser
from app.settings import get_settings

logger = logging.getLogger(__name__)

AGENTS_FUNCTION = "run_agents"
Kind = Literal["underwriting", "lm"]
FAILED_MESSAGE = "The agents could not be run."


class NothingToRerunError(LookupError):
    """There is no run (or no waterfall) whose agent could be re-run."""


async def start_agents(
    session: AsyncSession,
    queue: JobQueue,
    user: CurrentUser,
    case_id: uuid.UUID,
    kind: Kind,
    agent: AgentName | None = None,
) -> Job:
    """Record the request and queue it. Commits, because the job is queued only after the rows."""
    if agent is not None:
        await _target_run(session, case_id, kind)  # 404 before anything is queued
    job = Job(kind=f"{kind}_agents", case_id=case_id, status=JobStatus.QUEUED)
    session.add(job)
    await session.flush()
    await audit.record(
        session,
        actor_id=uuid.UUID(user.id),
        role=user.role.value,
        action=f"{kind}.agents_requested",
        entity_type="job",
        entity_id=job.id,
        case_id=case_id,
        after={"agent": agent.value if agent else "all"},
    )
    await session.commit()
    try:
        await queue.enqueue(
            AGENTS_FUNCTION,
            str(job.id),
            user.id,
            kind,
            agent.value if agent else None,
            job_id=str(job.id),
        )
    except Exception as exc:
        logger.warning("queueing job %s failed: %s", job.id, type(exc).__name__)
        job.status, job.error = JobStatus.FAILED, "The request was saved but could not be queued."
        await session.commit()
        raise UploadFailedError(
            "queue_unavailable", "The request was saved but could not be queued. Please try again."
        ) from exc
    await session.refresh(job)
    return job


async def _target_run(session: AsyncSession, case_id: uuid.UUID, kind: Kind) -> AnalysisRun:
    if kind == "underwriting":
        from app.agents.underwriting import latest_underwriting_run

        run = await latest_underwriting_run(session, case_id)
    else:
        from app.services.reports import latest_waterfall_run

        run = await latest_waterfall_run(session, case_id)
    if run is None:
        raise NothingToRerunError(kind)
    return run


async def run_agents_job(
    factory: async_sessionmaker[AsyncSession],
    job_id: uuid.UUID,
    user_id: uuid.UUID | None,
    kind: Kind,
    agent: str | None,
    **deps: Any,
) -> None:
    """What the worker runs. ``deps`` (gateway, store) are for tests."""
    from app.agents.lm import run_lm_agents
    from app.agents.underwriting import run_underwriting

    rerun = AgentName(agent) if agent else None
    async with factory() as session:
        job = await session.get(Job, job_id)
        if job is None or job.case_id is None:
            raise LookupError(f"agents job {job_id} does not exist")
        case_id = job.case_id
        job.status, job.stage, job.progress = JobStatus.RUNNING, "agents", 0.2
        job.attempts += 1
        await session.commit()
        try:
            if kind == "underwriting":
                run = await _target_run(session, case_id, kind) if rerun else None
                report = await run_underwriting(
                    session, case_id, user_id=user_id, run=run, rerun=rerun, **deps
                )
            else:
                run = await _target_run(session, case_id, kind)
                report = await run_lm_agents(session, run, rerun=rerun, **deps)
            job.status, job.stage, job.progress, job.error = JobStatus.SUCCEEDED, "done", 1.0, None
            await audit.record(
                session,
                actor_id=None,
                role="worker",
                action=f"{kind}.report_written",
                entity_type="report",
                entity_id=report.id,
                case_id=case_id,
                after={"version": report.version, "agent": agent or "all"},
            )
            await session.commit()
        except Exception as exc:
            await session.rollback()
            logger.warning("agents job failed job=%s: %s", job_id, type(exc).__name__)
            failed = await session.get(Job, job_id)
            if failed is not None:
                failed.status, failed.error = JobStatus.FAILED, FAILED_MESSAGE
                await session.commit()


async def run_lm_after_rules(session: AsyncSession, run: AnalysisRun, **deps: Any) -> str:
    """The LM agents on a fresh waterfall run. Skipped without a model (``PIPELINE_LLM=fake``);
    a failure is logged and leaves the waterfall as it is."""
    if not deps and get_settings().pipeline_llm == "fake":
        return "skipped"
    from app.agents.lm import run_lm_agents

    try:
        await run_lm_agents(session, run, **deps)
        await session.commit()
    except Exception as exc:
        await session.rollback()
        logger.warning("LM agents failed run=%s: %s", run.id, type(exc).__name__)
        return "failed"
    return "written"

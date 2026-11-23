"""Reading a hardship letter and confirming the reading (Feature Design 7.2, 7.5 and 7.7).

``start_reading`` records the request (a job) and queues it. ``run_hardship_job`` is what the worker
runs: read the letter into a profile through a ``HardshipReader``, check every quote in code, store
it as a new run (source ``model``; the seeded sample stays as history), then build the budget from
the case's documents, which is plain code. The only model calls are the reading and the labelling of
the bank statement lines.

``confirm_items`` is the specialist confirming or correcting the reading's judgements (reason,
onset, duration, intent) that the investor rules rely on (Feature 8). The reading is never
overwritten (rule 6): a confirmation is added beside each item with the value as read, the value
confirmed, who, when and why, and an audit event records it. Rules treat an item nobody has
confirmed as unconfirmed.

The reader sits behind a protocol so tests use a stub and the demo can use the real task.
"""

from __future__ import annotations

import logging
import re
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.enums import HardshipSource, JobStatus
from app.db.models import AnalysisRun, HardshipProfile, Job
from app.llm.checks import QuoteCheck
from app.llm.gateway import Gateway
from app.llm.hardship import read_hardship_letter
from app.llm.tasks import DocumentLine
from app.prompts.schemas.hardship import HardshipConfig
from app.prompts.schemas.hardship import HardshipProfile as ReadProfile
from app.services import audit, budget_runs, hardship_runs
from app.services.analysis_config import AnalysisConfig, get_analysis_config
from app.services.case_facts import load_case_documents
from app.services.documents import UploadFailedError
from app.services.pipeline import cause_chain
from app.services.queue import HARDSHIP_FUNCTION, JobQueue
from app.services.security import CurrentUser
from app.services.transaction_labels import TransactionLabeller, get_labeller

logger = logging.getLogger(__name__)

HARDSHIP_JOB_KIND = "hardship_reading"
READ_FAILED = "The hardship letter could not be read."
BUDGET_FAILED = "The letter was read, but the budget could not be completed."
CONFIRMED_LABEL = "reviewer-confirmed"
APPLICATION = "mortgage_assistance_application"
ITEMS = ("primary_reason", "onset", "duration", "intent")
# The part of each item a person confirms.
VALUE_KEY = {
    "primary_reason": "category",
    "onset": "month",
    "duration": "category",
    "intent": "category",
}
ALLOWED = {
    "duration": {"temporary", "long_term", "unknown"},
    "intent": {"keep", "sell", "unsure"},
}
MONTH = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")


class HardshipError(Exception):
    """A request the reading cannot honour. ``status`` and ``code`` are for the API."""

    def __init__(self, status: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status, self.code, self.message = status, code, message


def _now() -> datetime:
    return datetime.now(UTC)


# --- the reader ------------------------------------------------------------------------------


@dataclass(frozen=True)
class HardshipReading:
    profile: ReadProfile
    checks: list[QuoteCheck]
    provider: str | None = None
    model: str | None = None


class HardshipReader(Protocol):
    async def read(
        self, lines: Sequence[DocumentLine], *, application_reasons: Sequence[str]
    ) -> HardshipReading:
        """Read the letter's numbered lines into a profile and check each quote against them."""
        ...


class LlmHardshipReader:
    """The real reader: Arindam's ``read_hardship_letter`` through the gateway."""

    def __init__(
        self,
        config: HardshipConfig | None = None,
        provider: str | None = None,
        gateway: Gateway | None = None,
    ) -> None:
        self.config, self.provider, self.gateway = config, provider, gateway

    async def read(
        self, lines: Sequence[DocumentLine], *, application_reasons: Sequence[str]
    ) -> HardshipReading:
        outcome = await read_hardship_letter(
            lines,
            application_reasons=application_reasons,
            config=self.config or hardship_runs.get_hardship_config(),
            provider=self.provider,
            gateway=self.gateway,
        )
        return HardshipReading(
            outcome.profile, outcome.quote_checks, outcome.call.provider, outcome.call.model
        )


def get_reader() -> HardshipReader:
    return LlmHardshipReader()


# --- starting a reading ----------------------------------------------------------------------


async def start_reading(
    session: AsyncSession, queue: JobQueue, user: CurrentUser, case_id: uuid.UUID
) -> Job:
    """Record the request, then queue it. Commits, because the job is queued only after the rows."""
    if await hardship_runs.load_letter(session, case_id) is None:
        raise HardshipError(409, "no_letter", "No hardship letter has been read for this case yet.")
    job = Job(kind=HARDSHIP_JOB_KIND, case_id=case_id, status=JobStatus.QUEUED)
    session.add(job)
    await session.flush()
    await audit.record(
        session,
        actor_id=uuid.UUID(user.id),
        role=user.role.value,
        action="hardship.reading_requested",
        entity_type="job",
        entity_id=job.id,
        case_id=case_id,
    )
    await session.commit()
    try:
        await queue.enqueue(HARDSHIP_FUNCTION, str(job.id), user.id, job_id=str(job.id))
    except Exception as exc:
        logger.warning("queueing job %s failed: %s", job.id, type(exc).__name__)
        job.status = JobStatus.FAILED
        job.error = "The reading was saved but could not be queued."
        await session.commit()
        raise UploadFailedError(
            "queue_unavailable", "The reading was saved but could not be queued. Please try again."
        ) from exc
    await session.refresh(job)
    return job


# --- the worker ------------------------------------------------------------------------------


async def run_hardship_job(
    factory: async_sessionmaker[AsyncSession],
    job_id: uuid.UUID,
    user_id: uuid.UUID | None,
    *,
    reader: HardshipReader | None = None,
    labeller: TransactionLabeller | None = None,
    config: AnalysisConfig | None = None,
) -> None:
    """What the worker runs: read the letter, store the profile, build the budget."""
    cfg = config or get_analysis_config()
    async with factory() as session:
        job = await session.get(Job, job_id)
        if job is None or job.case_id is None:
            raise LookupError(f"hardship job {job_id} does not exist")
        case_id = job.case_id
        job.status, job.stage, job.progress = JobStatus.RUNNING, "read", 0.1
        job.attempts += 1
        await session.commit()
        stored: HardshipProfile | None = None
        try:
            letter = await hardship_runs.load_letter(session, case_id)
            if letter is None:
                raise HardshipError(409, "no_letter", "no letter")
            documents = await load_case_documents(session, case_id)
            application = next(
                (d for d in documents if d.doc_type == APPLICATION and d.usable), None
            )
            reasons = [
                row["reason"].text
                for row in (application.rows("hardship_reasons_").values() if application else [])
                if "reason" in row and row["reason"].text
            ]
            reading = await (reader or get_reader()).read(letter.lines, application_reasons=reasons)
            job.stage, job.progress = "save", 0.6
            hardship_config = hardship_runs.get_hardship_config()
            stored = await hardship_runs.store_profile(
                session,
                case_id=case_id,
                document_id=letter.document_id,
                profile=reading.profile,
                checks=reading.checks,
                config=hardship_config,
                source=HardshipSource.MODEL,
                created_by=user_id,
            )
            await session.commit()
        except Exception as exc:
            await session.rollback()
            logger.warning("hardship reading failed job=%s: %s", job_id, cause_chain(exc))
            await _fail(session, job_id, READ_FAILED)
            return
        try:
            job.stage, job.progress = "budget", 0.8
            run = await session.get(AnalysisRun, stored.run_id)
            assert run is not None
            await budget_runs.compute_for_run(
                session, run, cfg=cfg, labeller=labeller or get_labeller()
            )
            job.status, job.stage, job.progress, job.error = JobStatus.SUCCEEDED, "done", 1.0, None
            await session.commit()
        except Exception as exc:
            await session.rollback()
            logger.warning("hardship budget failed job=%s: %s", job_id, cause_chain(exc))
            await _fail(session, job_id, BUDGET_FAILED)


async def _fail(session: AsyncSession, job_id: uuid.UUID, message: str) -> None:
    job = await session.get(Job, job_id)
    if job is not None:
        job.status, job.error = JobStatus.FAILED, message
        await session.commit()


# --- confirmations ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ItemConfirmation:
    """One item the specialist confirms as read (``value`` None) or corrects (``value`` given)."""

    value: str | None = None
    reason: str | None = None


def _checked_value(item: str, value: str, config: HardshipConfig) -> str:
    if item == "primary_reason" and value not in config.keys:
        raise HardshipError(422, "invalid_value", f"{value!r} is not a hardship category.")
    if item == "onset" and not MONTH.match(value):
        raise HardshipError(422, "invalid_value", "Onset is a month written YYYY-MM.")
    if item in ALLOWED and value not in ALLOWED[item]:
        raise HardshipError(422, "invalid_value", f"{value!r} is not a valid {item}.")
    return value


async def confirm_items(
    session: AsyncSession,
    user: CurrentUser,
    case_id: uuid.UUID,
    confirmations: Mapping[str, ItemConfirmation],
    *,
    config: HardshipConfig | None = None,
) -> hardship_runs.HardshipView:
    """Confirm or correct the newest reading's items. A correction needs a reason. The value as
    read stays in the item; the confirmation is added beside it, with who, when and why."""
    config = config or hardship_runs.get_hardship_config()
    view = await hardship_runs.latest(session, case_id)
    if view is None:
        raise HardshipError(404, "not_found", "No hardship assessment has been made for this case")
    if not confirmations:
        raise HardshipError(422, "nothing_to_confirm", "Name at least one item to confirm.")
    profile = view.profile
    actor, now = uuid.UUID(user.id), _now()
    before: dict[str, Any] = {}
    after: dict[str, Any] = {}
    updated: dict[str, dict[str, Any]] = {}
    for item, given in confirmations.items():
        current: dict[str, Any] = getattr(profile, item)
        read = current.get(VALUE_KEY[item])
        value = given.value if given.value is not None else read
        reason = (given.reason or "").strip() or None
        if value is None:
            raise HardshipError(
                422, "invalid_value", f"The letter did not give {item}: say what it is."
            )
        value = _checked_value(item, value, config)
        corrected = value != read
        if corrected and reason is None:
            raise HardshipError(422, "reason_required", f"Changing {item} needs a reason.")
        before[item] = (current.get("confirmation") or {}).get("value", read)
        after[item] = {
            "value": value,
            "read": read,
            "status": "corrected" if corrected else "confirmed",
            "reason": reason,
        }
        updated[item] = {
            **current,
            "confirmation": {
                "status": "corrected" if corrected else "confirmed",
                "value": value,
                "original": read,
                "reason": reason,
                "by": str(actor),
                "at": now.isoformat(),
                "label": CONFIRMED_LABEL,
            },
        }
    for item, data in updated.items():
        setattr(profile, item, data)  # a new dict, so the change is tracked
    profile.confirmed_by, profile.confirmed_at = actor, now
    await session.flush()
    await audit.record(
        session,
        actor_id=actor,
        role=user.role.value,
        action="hardship.confirmed",
        entity_type="hardship_profile",
        entity_id=profile.id,
        case_id=case_id,
        before=before,
        after=after,
        reason="; ".join(f"{i}: {a['reason']}" for i, a in after.items() if a["reason"]) or None,
    )
    # The budget's consistency checks use the confirmed values, so they update at once (no model).
    await budget_runs.compute_for_run(session, view.run)
    await session.commit()
    refreshed = await hardship_runs.latest(session, case_id)
    assert refreshed is not None
    return refreshed


def effective_values(profile: HardshipProfile) -> dict[str, tuple[str | None, bool]]:
    """Each item's value and whether a person has confirmed it: ``(value, confirmed)``. The rules
    engine uses the value only when it is confirmed (Feature Design 8.2 step 1)."""
    out: dict[str, tuple[str | None, bool]] = {}
    for item in ITEMS:
        data: dict[str, Any] = getattr(profile, item)
        confirmation = data.get("confirmation")
        if confirmation:
            out[item] = (confirmation["value"], True)
        else:
            out[item] = (data.get(VALUE_KEY[item]), False)
    return out

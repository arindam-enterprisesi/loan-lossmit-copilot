"""Human review (CPS-09): confirm, correct or reject an extracted value, and change a type.

A correction never overwrites (CLAUDE.md rule 6): ``original_value`` stays, ``value`` and
``normalized_value`` change, and the audit event records who changed what, when and why. Every
change bumps the field's ``version``; a request that carries an older version is a conflict, so two
reviewers cannot silently overwrite each other (DI-E803).

After a review the checks run again in the same transaction with NO model call: flags, certainty,
status and summary all follow the new value. The system records that a person reviewed something;
it decides nothing.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.enums import DocTypeSource, DocumentStatus, FlagStatus, JobStatus, ReviewStatus
from app.db.models import Document, ExtractionRun, Job
from app.db.models import Field as FieldRow
from app.services import audit, flags
from app.services.document_config import (
    DocumentFieldsConfig,
    ValidationConfig,
    get_document_fields,
    get_validation_config,
)
from app.services.documents import PROCESSING_JOB_KIND, UploadFailedError
from app.services.extraction import active_run
from app.services.normalize import normalize, stored_text
from app.services.pipeline import refresh_document
from app.services.queue import PROCESS_FUNCTION, JobQueue
from app.services.security import CurrentUser

logger = logging.getLogger(__name__)

Action = Literal["confirm", "correct", "reject"]
_STATUS = {
    "confirm": ReviewStatus.CONFIRMED,
    "correct": ReviewStatus.CORRECTED,
    "reject": ReviewStatus.REJECTED,
}
_KIND_NAMES = {
    "amount": "an amount",
    "date": "a date",
    "id_last4": "an ID number",
    "number": "a number",
}


class FieldNotFoundError(Exception):
    """There is no such field in the document's active run."""


class EditConflictError(Exception):
    """Someone changed the field after the version the caller saw."""


class InvalidValueError(Exception):
    """A corrected value cannot be read as the field's kind (for example not an amount)."""


async def field_in_active_run(
    session: AsyncSession, document_id: uuid.UUID, name: str
) -> tuple[ExtractionRun, FieldRow] | None:
    run = await active_run(session, document_id)
    if run is None:
        return None
    row = await session.scalar(
        sa.select(FieldRow).where(FieldRow.run_id == run.id, FieldRow.name == name)
    )
    return (run, row) if row is not None else None


def _snapshot(row: FieldRow) -> dict[str, object]:
    return {
        "value": row.value,
        "normalized_value": row.normalized_value,
        "review_status": row.review_status.value,
        "version": row.version,
    }


async def review_field(
    session: AsyncSession,
    user: CurrentUser,
    document: Document,
    name: str,
    *,
    action: Action,
    expected_version: int,
    value: str | None = None,
    reason: str | None = None,
    cfg: DocumentFieldsConfig | None = None,
    rules: ValidationConfig | None = None,
) -> FieldRow:
    """Confirm, correct or reject one field. Flushes; the caller commits."""
    cfg = cfg or get_document_fields()
    found = await field_in_active_run(session, document.id, name)
    if found is None:
        raise FieldNotFoundError(name)
    run, row = found
    if row.version != expected_version:
        raise EditConflictError(name)

    changes: dict[str, object] = {
        "review_status": _STATUS[action],
        "reviewed_by": uuid.UUID(user.id),
        "reviewed_at": datetime.now(UTC),
        "review_reason": reason,
    }
    if action == "correct":
        kind = cfg.kind_of(run.doc_type, name)
        text = stored_text(kind, value)
        normalized = normalize(kind, text) if text else None
        if not text or (kind in _KIND_NAMES and normalized is None):
            wanted = _KIND_NAMES.get(kind, "a value")
            raise InvalidValueError(f"{cfg.field_label(run.doc_type, name)} must be {wanted}")
        changes["value"], changes["normalized_value"] = text, normalized  # original_value stays

    before = _snapshot(row)
    updated = await session.execute(
        sa.update(FieldRow)
        .where(FieldRow.id == row.id, FieldRow.version == expected_version)
        .values(**changes, version=expected_version + 1)
        .execution_options(synchronize_session=False)
    )
    if updated.rowcount == 0:  # type: ignore[attr-defined]
        raise EditConflictError(name)  # lost a race with another reviewer
    await session.refresh(row)

    if action == "confirm":  # the person has seen the flags and accepts the value
        await flags.close_flags(
            session,
            entity_type="field",
            entity_ids=[row.id],
            codes=None,
            status=FlagStatus.OVERRIDDEN,
            reason=reason or "confirmed by reviewer",
            resolved_by=uuid.UUID(user.id),
        )
    await audit.record(
        session,
        actor_id=uuid.UUID(user.id),
        role=user.role.value,
        action=f"field.{_STATUS[action].value}",
        entity_type="field",
        entity_id=row.id,
        case_id=document.case_id,
        before={"name": name, **before},
        after={"name": name, **_snapshot(row)},
        reason=reason,
    )
    await refresh_document(
        session,
        document.id,
        rules or get_validation_config(),
        cfg,
        actor_id=uuid.UUID(user.id),
        role=user.role.value,
    )
    return row


@dataclass(frozen=True)
class TypeChange:
    document: Document
    job: Job | None  # None when the type was only confirmed (no new extraction needed)


async def set_document_type(
    session: AsyncSession,
    queue: JobQueue,
    user: CurrentUser,
    document: Document,
    doc_type: str,
    reason: str | None,
) -> TypeChange:
    """Confirm or change the type. A change re-queues extract, validate and ready.

    Commits, because the job must be queued only after the change is saved.
    """
    run = await active_run(session, document.id)
    unchanged = run is not None and run.doc_type == doc_type and document.doc_type == doc_type
    before = {"doc_type": document.doc_type, "source": _value(document.doc_type_source)}
    document.doc_type = doc_type
    document.doc_type_source = DocTypeSource.USER
    await flags.close_flags(
        session,
        entity_type="document",
        entity_ids=[document.id],
        codes=("DI-W501", "DI-W502"),
        status=FlagStatus.RESOLVED,
        reason=reason or "type chosen by reviewer",
        resolved_by=uuid.UUID(user.id),
    )
    job: Job | None = None
    if not unchanged:
        document.status = DocumentStatus.PROCESSING
        job = Job(
            kind=PROCESSING_JOB_KIND,
            case_id=document.case_id,
            document_id=document.id,
            status=JobStatus.QUEUED,
        )
        session.add(job)
    await session.flush()
    await audit.record(
        session,
        actor_id=uuid.UUID(user.id),
        role=user.role.value,
        action="document.type_set",
        entity_type="document",
        entity_id=document.id,
        case_id=document.case_id,
        before=before,
        after={"doc_type": doc_type, "source": "user", "extraction_queued": job is not None},
        reason=reason,
    )
    await session.commit()
    if job is None:
        return TypeChange(document, None)
    try:
        await queue.enqueue(
            PROCESS_FUNCTION,
            str(job.id),
            [str(document.id)],
            ["extract", "validate", "ready"],
            True,
            job_id=str(job.id),
        )
    except Exception as exc:
        logger.warning("queueing job %s failed: %s", job.id, type(exc).__name__)
        job.status = JobStatus.FAILED
        job.error = "The type was saved but extraction could not be queued."
        await session.commit()
        raise UploadFailedError(
            "queue_unavailable", "The type was saved but could not be queued. Please try again."
        ) from exc
    await session.refresh(job)
    return TypeChange(document, job)


def _value(member: DocTypeSource | None) -> str | None:
    return member.value if member else None

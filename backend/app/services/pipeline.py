"""The document pipeline: ingest -> classify -> extract -> validate -> ready (Feature 1).

One arq job per upload runs each of its documents through these stages in order. Every stage is its
own function that REPLACES its own output, so it is safe to run twice and can be run alone (a type
change re-runs extract, validate and ready). Progress is (stages done) / (stages x documents).

  ingest    the file into pages and numbered lines (``app.services.ingestion``)
  classify  the type, from the lines only; applied automatically only when certain (FSD 4.4)
  extract   a NEW extraction run with the fields, each with the lines it came from
  validate  the checks in code (``app.services.validation``) -> flags; certainty per field
  ready     the document's status, template summary, borrower and period

A document ends ``needs_review`` if anything is left for a person (an open warning, a low-certainty
or missing value), ``reviewed`` if not, ``type_needed`` if a person must choose its type, or
``failed``. The pipeline never decides anything about a borrower; it only reads and checks.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Sequence
from dataclasses import dataclass

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.enums import (
    Certainty,
    DocTypeSource,
    DocumentStatus,
    FlagSeverity,
    FlagStatus,
    JobStatus,
)
from app.db.models import Document, Job
from app.db.models import Field as FieldRow
from app.llm.gateway import GatewayError
from app.services import audit, flags
from app.services.classification import (
    Classifier,
    PipelineUnavailableError,
    decide_type,
)
from app.services.document_config import (
    DocumentFieldsConfig,
    ValidationConfig,
    get_document_fields,
    get_validation_config,
)
from app.services.extraction import (
    active_run,
    document_facts,
    load_doc_lines,
    load_validation_input,
    persist_extraction,
    summary_for,
)
from app.services.extractor import Extractor
from app.services.ingestion import INGEST_FLAGS, OcrAdapter, ingest_document
from app.services.validation import validate
from app.storage import Storage

logger = logging.getLogger(__name__)


def cause_chain(exc: BaseException) -> str:
    """The class names along an exception's causes, ``GatewayError <- ProviderCallError <- ...``.

    Never the messages: a provider's message can quote the request, and the request is document
    text (CLAUDE.md: logs hold IDs, task names and counts, never document text). The class names
    are enough to tell a permissions error from a timeout.
    """
    names: list[str] = []
    seen: set[int] = set()
    err: BaseException | None = exc
    while err is not None and id(err) not in seen and len(names) < 6:
        seen.add(id(err))
        names.append(type(err).__name__)
        err = err.__cause__ or err.__context__
    return " <- ".join(names)


STAGES = ("ingest", "classify", "extract", "validate", "ready")
READ_FLAGS = (
    "DI-E401",
    "DI-E801",
)  # raised by classify/extract/crashes; closed when a later run works
TYPE_FLAGS = ("DI-W501", "DI-W502")
UNREADABLE = "the document could not be read reliably"


@dataclass(frozen=True)
class Readers:
    """Everything the stages need that is not the database."""

    storage: Storage
    ocr: OcrAdapter
    classifier: Classifier
    extractor: Extractor
    dpi: int
    rules: ValidationConfig
    cfg: DocumentFieldsConfig


@dataclass(frozen=True)
class StageOutcome:
    proceed: bool = True  # False: skip this document's remaining stages
    failure: str | None = None  # why the document failed (shown in the job's error)


async def _document(session: AsyncSession, document_id: uuid.UUID) -> Document:
    document = await session.get(Document, document_id)
    if document is None:
        raise LookupError(f"document {document_id} does not exist")
    return document


async def _fail_read(
    session: AsyncSession, document: Document, rules: ValidationConfig, reason: str = UNREADABLE
) -> StageOutcome:
    """The reader could not read the document (DI-E401): flag it, mark it failed, move on."""
    severity, message = rules.flag("DI-E401")
    await flags.raise_flag(
        session,
        case_id=document.case_id,
        entity_type="document",
        entity_id=document.id,
        code="DI-E401",
        severity=severity,
        message=message,
    )
    document.status = DocumentStatus.FAILED
    await session.flush()
    return StageOutcome(proceed=False, failure=reason)


# --- the stages -----------------------------------------------------------------------------


async def ingest_stage(
    session: AsyncSession, readers: Readers, document_id: uuid.UUID
) -> StageOutcome:
    result = await ingest_document(
        session, readers.storage, readers.ocr, document_id, dpi=readers.dpi
    )
    return StageOutcome(proceed=True) if result.ok else StageOutcome(False, result.reason)


async def classify_stage(
    session: AsyncSession, readers: Readers, document_id: uuid.UUID
) -> StageOutcome:
    document = await _document(session, document_id)
    if document.doc_type and document.doc_type_source is DocTypeSource.USER:
        return StageOutcome()  # a person set the type: never overwritten, no model call
    lines = await load_doc_lines(session, document.id)
    try:
        result = await readers.classifier.classify(lines)
    except (GatewayError, PipelineUnavailableError) as exc:
        logger.warning("classify failed document=%s: %s", document.id, cause_chain(exc))
        return await _fail_read(session, document, readers.rules)

    decision = decide_type(document.declared_type, result)
    document.doc_type_certainty = Certainty(result.certainty)
    await flags.close_flags(
        session,
        entity_type="document",
        entity_ids=[document.id],
        codes=(*TYPE_FLAGS, *READ_FLAGS),
        status=FlagStatus.RESOLVED,
        reason="type decided",
    )
    if decision.flag:
        meta = await flags.load_line_meta(session, document.id)
        evidence = flags.build_evidence(document.id, result.justification_line_ids, meta) or {}
        evidence.update(
            predicted=decision.predicted, selected=decision.selected, certainty=result.certainty
        )
        values = {"predicted": readers.cfg.type_label(decision.predicted)} | {
            "selected": readers.cfg.type_label(decision.selected or "")
        }
        severity, message = readers.rules.flag(decision.flag, **values)
        await flags.raise_flag(
            session,
            case_id=document.case_id,
            entity_type="document",
            entity_id=document.id,
            code=decision.flag,
            severity=severity,
            message=message,
            evidence=evidence,
        )
    if decision.needs_choice:
        document.doc_type = None
        document.doc_type_source = None
        document.status = DocumentStatus.TYPE_NEEDED
    else:
        document.doc_type = decision.doc_type
        document.doc_type_source = DocTypeSource(decision.source)
        document.status = DocumentStatus.PROCESSING
    await session.flush()
    await audit.record(
        session,
        actor_id=None,
        role="worker",
        action="document.classified",
        entity_type="document",
        entity_id=document.id,
        case_id=document.case_id,
        after={
            "doc_type": result.doc_type,
            "certainty": result.certainty,
            "applied": decision.doc_type,
            "flag": decision.flag,
            "provider": result.provider,
            "model": result.model,
            "unknown_line_ids": result.unknown_line_ids,
        },
    )
    return StageOutcome(proceed=not decision.needs_choice)


async def extract_stage(
    session: AsyncSession, readers: Readers, document_id: uuid.UUID, *, force: bool = False
) -> StageOutcome:
    document = await _document(session, document_id)
    if not document.doc_type:
        return StageOutcome(proceed=False)
    run = await active_run(session, document.id)
    if run is not None and run.doc_type == document.doc_type and not force:
        return StageOutcome()  # already extracted for this type: no second model call
    lines = await load_doc_lines(session, document.id)
    try:
        outcome = await readers.extractor.extract(document.doc_type, lines)
    except (GatewayError, PipelineUnavailableError) as exc:
        logger.warning("extract failed document=%s: %s", document.id, cause_chain(exc))
        return await _fail_read(session, document, readers.rules)
    run = await persist_extraction(session, document, document.doc_type, outcome, readers.cfg)
    await flags.close_flags(
        session,
        entity_type="document",
        entity_ids=[document.id],
        codes=READ_FLAGS,
        status=FlagStatus.RESOLVED,
        reason="read successfully",
    )
    await audit.record(
        session,
        actor_id=None,
        role="worker",
        action="document.extracted",
        entity_type="document",
        entity_id=document.id,
        case_id=document.case_id,
        after={
            "run_id": str(run.id),
            "doc_type": run.doc_type,
            "provider": run.provider,
            "model": run.model,
            "fields": len(outcome.fields),
        },
    )
    return StageOutcome()


async def validate_stage(
    session: AsyncSession,
    document_id: uuid.UUID,
    rules: ValidationConfig,
    cfg: DocumentFieldsConfig,
    *,
    actor_id: uuid.UUID | None = None,
    role: str = "worker",
) -> StageOutcome:
    """Run the checks again and bring flags, certainty and the document's facts up to date."""
    document = await _document(session, document_id)
    run = await active_run(session, document.id)
    if run is None:
        return StageOutcome(proceed=False)
    inp = await load_validation_input(session, document, run, cfg)
    report = validate(inp, rules, cfg)
    rows = (
        (await session.execute(sa.select(FieldRow).where(FieldRow.run_id == run.id)))
        .scalars()
        .all()
    )
    for row in rows:
        final = Certainty(report.certainty.get(row.name, row.certainty.value))
        if row.certainty is not final:
            row.certainty = final
    await session.flush()
    await flags.sync_flags(session, document, report.findings, {r.name: r.id for r in rows})

    facts = document_facts(run.doc_type, inp.fields, cfg)
    if facts.borrower:
        document.borrower = facts.borrower
    if facts.period_start and facts.period_end:
        document.period_start, document.period_end = facts.period_start, facts.period_end
    await session.flush()
    await audit.record(
        session,
        actor_id=actor_id,
        role=role,
        action="document.validated",
        entity_type="document",
        entity_id=document.id,
        case_id=document.case_id,
        after={"flags": sorted({f.code for f in report.findings if f.marks_review})},
    )
    return StageOutcome()


async def needs_review(session: AsyncSession, document: Document) -> bool:
    """Is anything left for a person? An open warning or error, or a low or missing value."""
    open_flags = await flags.open_flags(session, document)
    if any(f.severity is not FlagSeverity.INFO for f in open_flags):
        return True
    run = await active_run(session, document.id)
    if run is None:
        return False
    low = await session.scalar(
        sa.select(sa.func.count())
        .select_from(FieldRow)
        .where(
            FieldRow.run_id == run.id,
            FieldRow.certainty == Certainty.LOW,
            FieldRow.review_status == "unreviewed",
        )
    )
    return bool(low)


async def ready_stage(
    session: AsyncSession, document_id: uuid.UUID, cfg: DocumentFieldsConfig
) -> StageOutcome:
    """Set the status and the template summary from the current fields."""
    document = await _document(session, document_id)
    run = await active_run(session, document.id)
    if run is None:
        return StageOutcome(proceed=False)
    inp = await load_validation_input(session, document, run, cfg)
    document.summary = summary_for(run.doc_type, inp.fields, cfg)
    document.status = (
        DocumentStatus.NEEDS_REVIEW
        if await needs_review(session, document)
        else DocumentStatus.REVIEWED
    )
    await session.flush()
    return StageOutcome()


async def refresh_document(
    session: AsyncSession,
    document_id: uuid.UUID,
    rules: ValidationConfig | None = None,
    cfg: DocumentFieldsConfig | None = None,
    *,
    actor_id: uuid.UUID | None = None,
    role: str = "worker",
) -> None:
    """Re-run validate and ready with no model call (after a correction)."""
    rules, cfg = rules or get_validation_config(), cfg or get_document_fields()
    await validate_stage(session, document_id, rules, cfg, actor_id=actor_id, role=role)
    await ready_stage(session, document_id, cfg)


async def run_stage(
    stage: str,
    session: AsyncSession,
    readers: Readers,
    document_id: uuid.UUID,
    *,
    force_extract: bool = False,
) -> StageOutcome:
    if stage == "ingest":
        return await ingest_stage(session, readers, document_id)
    if stage == "classify":
        return await classify_stage(session, readers, document_id)
    if stage == "extract":
        return await extract_stage(session, readers, document_id, force=force_extract)
    if stage == "validate":
        return await validate_stage(session, document_id, readers.rules, readers.cfg)
    if stage == "ready":
        return await ready_stage(session, document_id, readers.cfg)
    raise ValueError(f"unknown stage {stage!r}")


# --- the job --------------------------------------------------------------------------------


async def _update_job(
    session_factory: async_sessionmaker[AsyncSession],
    job_id: uuid.UUID,
    *,
    status: JobStatus | None = None,
    error: str | None = None,
    progress: float | None = None,
    stage: str | None = None,
) -> None:
    async with session_factory() as session:
        job = await session.get(Job, job_id)
        if job is None:
            return
        if status is not None:
            job.status = status
            job.error = error
        if progress is not None:
            job.progress = progress
        if stage is not None:
            job.stage = stage
        await session.commit()


async def _record_crash(
    session_factory: async_sessionmaker[AsyncSession],
    document_id: uuid.UUID,
    stage: str,
    rules: ValidationConfig,
) -> None:
    """A stage crashed: flag it (DI-E801) so the user can re-run that stage."""
    async with session_factory() as session:
        document = await session.get(Document, document_id)
        if document is None:
            return
        severity, message = rules.flag("DI-E801", stage=stage)
        await flags.raise_flag(
            session,
            case_id=document.case_id,
            entity_type="document",
            entity_id=document.id,
            code="DI-E801",
            severity=severity,
            message=message,
        )
        document.status = DocumentStatus.FAILED
        await session.commit()


async def run_pipeline_job(
    session_factory: async_sessionmaker[AsyncSession],
    readers: Readers,
    job_id: uuid.UUID,
    document_ids: Sequence[uuid.UUID],
    *,
    stages: Sequence[str] | None = None,
    force_extract: bool = False,
) -> None:
    """Take each document through the stages, keeping the job's progress and status current.

    The job ends ``succeeded`` if no document failed (one waiting for its type to be chosen is not
    a failure) and ``failed`` otherwise, with a message per failed file; the other documents keep
    what was read from them.
    """
    chosen = tuple(stages) if stages else STAGES
    unknown = [s for s in chosen if s not in STAGES]
    if unknown:
        raise ValueError(f"unknown stages {unknown}")
    async with session_factory() as session:
        job = await session.get(Job, job_id)
        if job is None:
            raise LookupError(f"job {job_id} does not exist")
        job.status, job.stage, job.progress, job.error = JobStatus.RUNNING, chosen[0], 0.0, None
        job.attempts += 1
        await session.commit()

    total = len(chosen) * len(document_ids)
    done = 0
    failures: list[str] = []
    for document_id in document_ids:
        for index, stage in enumerate(chosen):
            try:
                async with session_factory() as session:
                    if index == 0 and stage != "ingest":  # a re-run of a later stage
                        document = await _document(session, document_id)
                        document.status = DocumentStatus.PROCESSING
                    outcome = await run_stage(
                        stage, session, readers, document_id, force_extract=force_extract
                    )
                    job = await session.get(Job, job_id)
                    if job is not None:
                        done += 1
                        job.stage, job.progress = stage, done / total
                    await session.commit()
            except Exception:
                logger.exception(
                    "stage crashed job=%s document=%s stage=%s", job_id, document_id, stage
                )
                await _record_crash(session_factory, document_id, stage, readers.rules)
                await _update_job(
                    session_factory,
                    job_id,
                    status=JobStatus.FAILED,
                    error="Reading the files stopped unexpectedly.",
                )
                raise
            if not outcome.proceed:
                done += len(chosen) - index - 1  # its remaining stages are skipped, not pending
                async with session_factory() as session:
                    document = await _document(session, document_id)
                    if outcome.failure:
                        failures.append(f"We couldn't use {document.file_name}: {outcome.failure}.")
                break
        await _update_job(session_factory, job_id, progress=done / total)

    if failures:
        await _update_job(
            session_factory, job_id, status=JobStatus.FAILED, error=" ".join(failures)
        )
    else:
        await _update_job(session_factory, job_id, status=JobStatus.SUCCEEDED, progress=1.0)


__all__ = [
    "INGEST_FLAGS",
    "STAGES",
    "Readers",
    "StageOutcome",
    "refresh_document",
    "run_pipeline_job",
]

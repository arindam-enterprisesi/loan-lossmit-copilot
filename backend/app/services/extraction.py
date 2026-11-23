"""Extraction results in the database: runs and fields, and what the checks and the summary read.

A fresh extraction creates a NEW run and new field rows. The previous run and any corrections made
on it stay as history (CLAUDE.md rule 6), and exactly one run per document is active.

What is stored for a field read from a document:
  value             the text as read (an identifier is already cut to its last four digits)
  normalized_value  its standard form: ``2083.61``, ``2026-09-27``, ``6032``
  original_value    the first normalised value. A correction changes ``value`` and
                    ``normalized_value`` but never this.
"""

from __future__ import annotations

import string
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.enums import Certainty, FlagSeverity, FlagStatus, ReviewStatus
from app.db.models import Document, ExtractionRun, Flag, Line, Page
from app.db.models import Field as FieldRow
from app.services.doc_lines import DocLine, doc_lines
from app.services.document_config import DocumentFieldsConfig
from app.services.extractor import ExtractionOutcome
from app.services.flags import LineMeta, load_line_meta
from app.services.normalize import display_value, normalize, parse_date, stored_text
from app.services.validation import FieldInput, LineInput, PageInput, ValidationInput

SUPERSEDED = "superseded by a newer extraction"


# --- from the extractor's answer to rows ----------------------------------------------------


@dataclass(frozen=True)
class PreparedField:
    name: str
    kind: str
    value: str | None
    normalized: str | None
    original: str | None
    certainty: str
    lines: list[str]
    required: bool


def prepare_fields(
    doc_type: str, outcome: ExtractionOutcome, cfg: DocumentFieldsConfig
) -> list[PreparedField]:
    """What to store per field: those read, then an empty row for any required one missed."""
    prepared: list[PreparedField] = []
    required = {f.name for f in cfg.required_fields(doc_type)}
    for name in [*outcome.fields, *(n for n in sorted(required) if n not in outcome.fields)]:
        read = outcome.fields.get(name)
        kind = cfg.kind_of(doc_type, name)
        value = stored_text(kind, read.value) if read else None
        normalized = normalize(kind, value) if value else None
        if read and read.sign == "-" and normalized and not normalized.startswith("-"):
            normalized = f"-{normalized}"  # an unsigned amount printed in a withdrawal column
        prepared.append(
            PreparedField(
                name=name,
                kind=kind,
                value=value,
                normalized=normalized,
                original=normalized if normalized is not None else value,
                certainty=(read.certainty if read else "low"),
                lines=list(read.lines) if read else [],
                required=name in required,
            )
        )
    return prepared


async def active_run(session: AsyncSession, document_id: uuid.UUID) -> ExtractionRun | None:
    return await session.scalar(
        sa.select(ExtractionRun).where(
            ExtractionRun.document_id == document_id, ExtractionRun.active.is_(True)
        )
    )


async def persist_extraction(
    session: AsyncSession,
    document: Document,
    doc_type: str,
    outcome: ExtractionOutcome,
    cfg: DocumentFieldsConfig,
) -> ExtractionRun:
    """Make a new active run with its fields. The old run stays, inactive, with its flags closed."""
    old = await active_run(session, document.id)
    if old is not None:
        old.active = False
        await session.flush()  # first, so the one-active-run index holds
        old_fields = sa.select(FieldRow.id).where(FieldRow.run_id == old.id)
        await session.execute(
            sa.update(Flag)
            .where(
                Flag.entity_type == "field",
                Flag.entity_id.in_(old_fields),
                Flag.status == FlagStatus.OPEN,
            )
            .values(status=FlagStatus.RESOLVED, reason=SUPERSEDED)
            .execution_options(synchronize_session=False)
        )
    run = ExtractionRun(
        document_id=document.id,
        doc_type=doc_type,
        active=True,
        prompt_id=outcome.prompt_id,
        provider=outcome.provider,
        model=outcome.model,
        signals=list(outcome.signals),
    )
    session.add(run)
    await session.flush()
    for field in prepare_fields(doc_type, outcome, cfg):
        session.add(
            FieldRow(
                document_id=document.id,
                run_id=run.id,
                name=field.name,
                value=field.value,
                normalized_value=field.normalized,
                original_value=field.original,
                certainty=Certainty(field.certainty),
                line_refs=field.lines,
                review_status=ReviewStatus.UNREVIEWED,
            )
        )
    await session.flush()
    return run


# --- from rows to what the checks read -------------------------------------------------------


async def load_doc_lines(session: AsyncSession, document_id: uuid.UUID) -> list[DocLine]:
    rows = await session.execute(
        sa.select(Line.line_ref, Line.text).where(Line.document_id == document_id)
    )
    return doc_lines((ref, text) for ref, text in rows.all())


async def load_validation_input(
    session: AsyncSession, document: Document, run: ExtractionRun, cfg: DocumentFieldsConfig
) -> ValidationInput:
    doc_type = run.doc_type
    fields = (
        (await session.execute(sa.select(FieldRow).where(FieldRow.run_id == run.id)))
        .scalars()
        .all()
    )
    required = {f.name for f in cfg.required_fields(doc_type)}
    inputs = {
        f.name: FieldInput(
            name=f.name,
            value=f.value,
            normalized=f.normalized_value,
            kind=cfg.kind_of(doc_type, f.name),
            lines=tuple(f.line_refs),
            certainty=f.certainty.value,
            review_status=f.review_status.value,
            required=f.name in required,
        )
        for f in fields
    }
    lines = (
        await session.execute(
            sa.select(Line.line_ref, Line.text, Line.confidence).where(
                Line.document_id == document.id
            )
        )
    ).all()
    pages = (
        await session.execute(
            sa.select(Page.page_no, Page.printed_page_label)
            .where(Page.document_id == document.id)
            .order_by(Page.page_no)
        )
    ).all()
    return ValidationInput(
        doc_type=doc_type,
        fields=inputs,
        lines={r: LineInput(r, text, conf) for r, text, conf in lines},
        pages=[PageInput(no, label) for no, label in pages],
        signals=list(run.signals),
    )


# --- summary and the document's own facts ----------------------------------------------------


class _Values(dict[str, str]):
    def __missing__(self, key: str) -> str:
        return "not found"


def summary_for(
    doc_type: str, fields: Mapping[str, FieldInput], cfg: DocumentFieldsConfig
) -> str | None:
    """The template summary (no AI): the type's template filled from the extracted values."""
    spec = cfg.spec(doc_type)
    if spec is None or not spec.summary:
        return None
    names = {f for _, f, _, _ in string.Formatter().parse(spec.summary) if f}
    values = _Values()
    for name in names:
        f = fields.get(name)
        shown = f.normalized if f and f.present else None
        values[name] = display_value(cfg.kind_of(doc_type, name), shown)
    return spec.summary.format_map(values)


@dataclass(frozen=True)
class DocumentFacts:
    borrower: str | None
    period_start: date | None
    period_end: date | None


def document_facts(
    doc_type: str, fields: Mapping[str, FieldInput], cfg: DocumentFieldsConfig
) -> DocumentFacts:
    """Who the document is about and the period it covers, for the case overview."""
    spec = cfg.spec(doc_type)
    if spec is None:
        return DocumentFacts(None, None, None)

    def text(name: str | None) -> str | None:
        f = fields.get(name) if name else None
        return f.normalized if f and f.present else None

    start, end = [*spec.period_fields, None, None][:2]
    return DocumentFacts(text(spec.borrower_field), parse_date(text(start)), parse_date(text(end)))


def prepared_to_inputs(doc_type: str, prepared: Sequence[PreparedField]) -> dict[str, FieldInput]:
    """The prepared fields as the checks receive them (for tests and previews, with no database)."""
    return {
        p.name: FieldInput(
            name=p.name,
            value=p.value,
            normalized=p.normalized,
            kind=p.kind,
            lines=tuple(p.lines),
            certainty=p.certainty,
            review_status="unreviewed",
            required=p.required,
        )
        for p in prepared
    }


# --- what GET .../extraction shows -----------------------------------------------------------


@dataclass(frozen=True)
class ExtractionView:
    run: ExtractionRun
    fields: list[tuple[FieldRow, list[Flag]]]  # flagged first; each with its open flags
    document_flags: list[Flag]
    meta: dict[str, LineMeta]


def _order(cfg: DocumentFieldsConfig, doc_type: str, name: str) -> tuple[int, int, str]:
    """The configured order: listed fields first, then transactions in order, then the rest."""
    spec = cfg.spec(doc_type)
    if spec:
        listed = [f.name for f in spec.fields]
        if name in listed:
            return (0, listed.index(name), name)
    match = cfg.transaction_match(doc_type, name)
    if match:
        parts = ["date", "description", "amount", "balance"]
        return (1, int(match[0]) * 4 + parts.index(match[1]), name)
    return (2, 0, name)


async def extraction_view(
    session: AsyncSession, document: Document, run: ExtractionRun, cfg: DocumentFieldsConfig
) -> ExtractionView:
    rows = (
        (await session.execute(sa.select(FieldRow).where(FieldRow.run_id == run.id)))
        .scalars()
        .all()
    )
    open_flags = (
        (
            await session.execute(
                sa.select(Flag).where(
                    Flag.case_id == document.case_id,
                    Flag.status == FlagStatus.OPEN,
                    sa.or_(
                        sa.and_(Flag.entity_type == "document", Flag.entity_id == document.id),
                        sa.and_(
                            Flag.entity_type == "field",
                            Flag.entity_id.in_([r.id for r in rows]),
                        ),
                    ),
                )
            )
        )
        .scalars()
        .all()
    )
    by_field: dict[uuid.UUID, list[Flag]] = {}
    for flag in open_flags:
        if flag.entity_type == "field":
            by_field.setdefault(flag.entity_id, []).append(flag)

    def rank(row: FieldRow) -> int:
        marks = [f for f in by_field.get(row.id, []) if f.severity is not FlagSeverity.INFO]
        if marks:
            return 0  # flagged first (FD 1.2)
        if row.certainty is Certainty.LOW and row.review_status is ReviewStatus.UNREVIEWED:
            return 1
        return 2

    ordered = sorted(rows, key=lambda r: (rank(r), _order(cfg, run.doc_type, r.name)))
    return ExtractionView(
        run=run,
        fields=[(r, by_field.get(r.id, [])) for r in ordered],
        document_flags=sorted(
            (f for f in open_flags if f.entity_type == "document"), key=lambda f: f.code
        ),
        meta=await load_line_meta(session, document.id),
    )

"""Flags: turn the checks' findings into rows, and keep the rows in step with the checks.

A flag is identified by what it is about and its rule: ``(entity_type, entity_id, code)`` (unique in
the database). Re-running the checks is idempotent:

  a failing check with no flag        creates an open flag
  a failing check with an open flag   updates its message and evidence
  a flag the SYSTEM closed            is reopened if its check fails again
  a flag a PERSON resolved/overrode   is left alone (their decision stands)
  an open flag whose check now passes is closed by the system ("check now passes")

Only the codes the checks own (``is_managed``) are closed this way; type and failure flags
(DI-W501, DI-W502, DI-E...) belong to the pipeline stage that raised them.
"""

from __future__ import annotations

import uuid
from collections.abc import Collection, Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.enums import FlagSeverity, FlagStatus
from app.db.models import Document, ExtractionRun, Flag, Line, Page
from app.db.models import Field as Field
from app.services.validation import Finding

FEATURE = "documents"
CHECK_CLEARED = "check now passes"
_OWNED = frozenset({"DI-W601", "DI-W604", "DI-W605", "DI-W701"})


def is_managed(code: str) -> bool:
    """Is this code raised and closed by the checks (as opposed to by a pipeline stage)?"""
    return code.startswith("DI-CHK-") or code in _OWNED


@dataclass(frozen=True)
class LineMeta:
    page: int
    bbox: dict[str, float] | None


async def load_line_meta(session: AsyncSession, document_id: uuid.UUID) -> dict[str, LineMeta]:
    rows = await session.execute(
        sa.select(Line.line_ref, Page.page_no, Line.bbox)
        .join(Page, Page.id == Line.page_id)
        .where(Line.document_id == document_id)
    )
    return {ref: LineMeta(page, bbox) for ref, page, bbox in rows.all()}


def union_box(boxes: Iterable[Mapping[str, float]]) -> dict[str, float] | None:
    found = list(boxes)
    if not found:
        return None
    return {
        "x0": min(b["x0"] for b in found),
        "y0": min(b["y0"] for b in found),
        "x1": max(b["x1"] for b in found),
        "y1": max(b["y1"] for b in found),
    }


def build_evidence(
    document_id: uuid.UUID,
    refs: Sequence[str],
    meta: Mapping[str, LineMeta],
    working: Mapping[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Where it is (first cited page, every cited line, their union box) and the working."""
    evidence: dict[str, Any] = {}
    known = [r for r in refs if r in meta]
    if known:
        page = meta[known[0]].page
        on_page = [meta[r] for r in known if meta[r].page == page]
        evidence = {
            "document_id": str(document_id),
            "page": page,
            "line_ids": list(refs),
            "bbox": union_box(m.bbox for m in on_page if m.bbox),
        }
    if working:
        evidence["working"] = dict(working)
    return evidence or None


async def raise_flag(
    session: AsyncSession,
    *,
    case_id: uuid.UUID,
    entity_type: str,
    entity_id: uuid.UUID,
    code: str,
    severity: str,
    message: str,
    evidence: dict[str, Any] | None = None,
    feature: str = FEATURE,
) -> Flag:
    """Create the flag, or bring the existing one up to date (see the rules above).

    ``feature`` says which feature raised it ("documents" for Feature 1, "income" for Feature 2).
    """
    existing = await session.scalar(
        sa.select(Flag).where(
            Flag.entity_type == entity_type, Flag.entity_id == entity_id, Flag.code == code
        )
    )
    if existing is None:
        flag = Flag(
            case_id=case_id,
            feature=feature,
            entity_type=entity_type,
            entity_id=entity_id,
            code=code,
            severity=FlagSeverity(severity),
            message=message,
            evidence=evidence,
        )
        session.add(flag)
        await session.flush()
        return flag
    person_decided = existing.status is FlagStatus.OVERRIDDEN or (
        existing.status is FlagStatus.RESOLVED and existing.resolved_by is not None
    )
    if person_decided:
        return existing
    existing.severity = FlagSeverity(severity)
    existing.message = message
    existing.evidence = evidence
    if existing.status is FlagStatus.RESOLVED:  # the system closed it; its check fails again
        existing.status = FlagStatus.OPEN
        existing.reason = None
    await session.flush()
    return existing


async def close_flags(
    session: AsyncSession,
    *,
    entity_type: str,
    entity_ids: Collection[uuid.UUID],
    codes: Collection[str] | None,
    status: FlagStatus,
    reason: str | None,
    resolved_by: uuid.UUID | None = None,
) -> int:
    """Close the open flags on these entities (all, or only these codes). Returns how many."""
    if not entity_ids:
        return 0
    query = (
        sa.update(Flag)
        .where(
            Flag.entity_type == entity_type,
            Flag.entity_id.in_(list(entity_ids)),
            Flag.status == FlagStatus.OPEN,
        )
        .values(status=status, resolved_by=resolved_by, reason=reason)
        .execution_options(synchronize_session=False)
    )
    if codes is not None:
        query = query.where(Flag.code.in_(list(codes)))
    result = await session.execute(query)
    return int(result.rowcount)  # type: ignore[attr-defined]


@dataclass(frozen=True)
class SyncResult:
    raised: int
    cleared: int


async def sync_flags(
    session: AsyncSession,
    document: Document,
    findings: Sequence[Finding],
    field_ids: Mapping[str, uuid.UUID],
) -> SyncResult:
    """Bring the document's check flags in line with ``findings`` (idempotent)."""
    meta = await load_line_meta(session, document.id)
    wanted: set[tuple[str, uuid.UUID, str]] = set()
    for finding in findings:
        on_field = finding.entity == "field" and finding.field in field_ids
        entity_type = "field" if on_field else "document"
        entity_id = field_ids[finding.field] if on_field and finding.field else document.id
        wanted.add((entity_type, entity_id, finding.code))
        await raise_flag(
            session,
            case_id=document.case_id,
            entity_type=entity_type,
            entity_id=entity_id,
            code=finding.code,
            severity=finding.severity,
            message=finding.message,
            evidence=build_evidence(document.id, finding.lines, meta, finding.working),
        )

    ids = list(field_ids.values())
    open_flags = (
        (
            await session.execute(
                sa.select(Flag).where(
                    Flag.case_id == document.case_id,
                    Flag.status == FlagStatus.OPEN,
                    sa.or_(
                        sa.and_(Flag.entity_type == "document", Flag.entity_id == document.id),
                        sa.and_(Flag.entity_type == "field", Flag.entity_id.in_(ids)),
                    ),
                )
            )
        )
        .scalars()
        .all()
    )
    cleared = 0
    for flag in open_flags:
        if is_managed(flag.code) and (flag.entity_type, flag.entity_id, flag.code) not in wanted:
            flag.status = FlagStatus.RESOLVED
            flag.resolved_by = None
            flag.reason = CHECK_CLEARED
            cleared += 1
    await session.flush()
    return SyncResult(raised=len(wanted), cleared=cleared)


async def open_flags(session: AsyncSession, document: Document) -> list[Flag]:
    """Every open flag about this document: its own and its active run's fields'."""
    field_ids = sa.text(
        "SELECT f.id FROM fields f JOIN extraction_runs r ON r.id = f.run_id "
        "WHERE r.document_id = :d AND r.active"
    ).bindparams(d=document.id)
    rows = await session.execute(
        sa.select(Flag).where(
            Flag.case_id == document.case_id,
            Flag.status == FlagStatus.OPEN,
            sa.or_(
                sa.and_(Flag.entity_type == "document", Flag.entity_id == document.id),
                sa.and_(Flag.entity_type == "field", Flag.entity_id.in_(field_ids)),
            ),
        )
    )
    return list(rows.scalars().all())


async def open_flags_by_document(
    session: AsyncSession, case_id: uuid.UUID, document_ids: Sequence[uuid.UUID]
) -> dict[uuid.UUID, list[Flag]]:
    """Open flags for several documents (their own and their active fields'), oldest first."""
    if not document_ids:
        return {}
    ids = list(document_ids)
    own = sa.select(Flag, Flag.entity_id.label("document_id")).where(
        Flag.case_id == case_id,
        Flag.status == FlagStatus.OPEN,
        Flag.entity_type == "document",
        Flag.entity_id.in_(ids),
    )
    on_fields = (
        sa.select(Flag, Field.document_id.label("document_id"))
        .join(Field, Field.id == Flag.entity_id)
        .join(ExtractionRun, ExtractionRun.id == Field.run_id)
        .where(
            Flag.case_id == case_id,
            Flag.status == FlagStatus.OPEN,
            Flag.entity_type == "field",
            ExtractionRun.active.is_(True),
            Field.document_id.in_(ids),
        )
    )
    grouped: dict[uuid.UUID, list[Flag]] = {i: [] for i in ids}
    for query in (own, on_fields):
        for flag, document_id in (await session.execute(query)).all():
            grouped[document_id].append(flag)
    for found in grouped.values():
        found.sort(key=lambda f: (f.created_at, f.code))
    return grouped

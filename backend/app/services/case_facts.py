"""A case's documents and their stored fields, as the analyses read them.

Income analysis and the completeness check both need the same thing: which documents the case has,
what type each is, who it is about, the period it covers, its active extraction run's values (the
person's corrections included, because ``normalized_value`` is updated by a correction) and which
document-level flags are open. This module loads that once and hands over plain dataclasses, so the
analyses themselves stay pure and testable without a database.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.enums import FlagStatus
from app.db.models import Document, ExtractionRun, Flag
from app.db.models import Field as FieldRow
from app.services.normalize import parse_amount, parse_date, parse_number


@dataclass(frozen=True)
class FieldFact:
    name: str
    value: str | None  # as read
    normalized: str | None  # the standard form (a correction updates it)
    lines: tuple[str, ...]
    review_status: str
    certainty: str

    @property
    def text(self) -> str | None:
        """The value to use: the normalised form, else what was read."""
        return self.normalized if self.normalized is not None else self.value


@dataclass(frozen=True)
class DocFacts:
    id: uuid.UUID
    file_name: str
    doc_type: str | None
    status: str
    borrower: str | None
    period_start: date | None
    period_end: date | None
    created_at: datetime
    fields: dict[str, FieldFact] = field(default_factory=dict)
    # Codes of the document's own open flags (DI-W701 means it is incomplete, and so on).
    open_flags: frozenset[str] = frozenset()

    @property
    def usable(self) -> bool:
        """Read successfully: a failed document, or one still waiting for a type, is not used."""
        return self.doc_type is not None and self.status not in {"failed", "type_needed"}

    def text(self, name: str | None) -> str | None:
        found = self.fields.get(name) if name else None
        return found.text if found else None

    def amount(self, name: str | None) -> Decimal | None:
        return parse_amount(self.text(name))

    def number(self, name: str | None) -> Decimal | None:
        return parse_number(self.text(name))

    def day(self, name: str | None) -> date | None:
        return parse_date(self.text(name))

    def lines_of(self, *names: str) -> tuple[str, ...]:
        refs: list[str] = []
        for name in names:
            for ref in self.fields[name].lines if name in self.fields else ():
                if ref not in refs:
                    refs.append(ref)
        return tuple(refs)

    def rows(self, prefix: str) -> dict[int, dict[str, FieldFact]]:
        """The numbered rows of a repeating group: ``rows("earnings_")[1]["hours"]``."""
        pattern = re.compile(rf"^{re.escape(prefix)}(\d+)_([a-z0-9_]+)$")
        rows: dict[int, dict[str, FieldFact]] = {}
        for name, fact in self.fields.items():
            found = pattern.match(name)
            if found:
                rows.setdefault(int(found.group(1)), {})[found.group(2)] = fact
        return dict(sorted(rows.items()))


async def load_case_documents(session: AsyncSession, case_id: uuid.UUID) -> list[DocFacts]:
    """Every document of the case, oldest upload first, with its active run's fields."""
    documents = (
        (
            await session.execute(
                sa.select(Document)
                .where(Document.case_id == case_id)
                .order_by(Document.created_at, Document.id)
            )
        )
        .scalars()
        .all()
    )
    ids = [d.id for d in documents]
    fields: dict[uuid.UUID, dict[str, FieldFact]] = {d.id: {} for d in documents}
    flags: dict[uuid.UUID, set[str]] = {d.id: set() for d in documents}
    if ids:
        rows = (
            (
                await session.execute(
                    sa.select(FieldRow)
                    .join(ExtractionRun, ExtractionRun.id == FieldRow.run_id)
                    .where(ExtractionRun.active.is_(True), ExtractionRun.document_id.in_(ids))
                    .order_by(FieldRow.name)
                )
            )
            .scalars()
            .all()
        )
        for row in rows:
            fields[row.document_id][row.name] = FieldFact(
                name=row.name,
                value=row.value,
                normalized=row.normalized_value,
                lines=tuple(row.line_refs or ()),
                review_status=row.review_status.value,
                certainty=row.certainty.value,
            )
        open_flags = await session.execute(
            sa.select(Flag.entity_id, Flag.code).where(
                Flag.entity_type == "document",
                Flag.entity_id.in_(ids),
                Flag.status == FlagStatus.OPEN,
            )
        )
        for entity_id, code in open_flags.all():
            flags[entity_id].add(code)
    return [
        DocFacts(
            id=d.id,
            file_name=d.file_name,
            doc_type=d.doc_type,
            status=d.status.value,
            borrower=d.borrower,
            period_start=d.period_start,
            period_end=d.period_end,
            created_at=d.created_at,
            fields=fields[d.id],
            open_flags=frozenset(flags[d.id]),
        )
        for d in documents
    ]

"""Extraction, field-review and type-change shapes, as in contracts/openapi.yaml.

``Field.value`` is the field's ``normalized_value`` (the contract says values are "exactly as
normalised by code") and ``original_value`` the first normalised value, so a reviewer sees
``2083.61`` against a corrected ``2033.61``. Only the contract's evidence keys are sent; the
working of a check stays in the database (and is shown by "Show working" in a later feature).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal, Self

from pydantic import BaseModel, Field, model_validator

from app.api.schemas.documents import (
    BoundingBox,
    DocumentSummaryOut,
    EvidenceOut,
    FlagOut,
    flag_from_row,
)
from app.api.schemas.jobs import JobOut
from app.db.enums import Certainty, DocumentType, ReviewStatus
from app.db.models import Field as FieldRow
from app.db.models import Flag
from app.services.flags import LineMeta, union_box


class FieldOut(BaseModel):
    name: str
    value: str | None
    original_value: str | None
    certainty: Certainty
    flags: list[FlagOut]
    evidence: EvidenceOut | None = None
    review_status: ReviewStatus
    reviewed_by: str | None = None
    reviewed_at: datetime | None = None
    review_reason: str | None = None
    version: int


class ExtractionOut(BaseModel):
    document_id: uuid.UUID
    run_id: uuid.UUID
    doc_type: DocumentType
    fields: list[FieldOut]
    flags: list[FlagOut]
    summary: str | None = None
    prompt_id: str | None = None
    provider: str | None = None
    model: str | None = None


class FieldReviewIn(BaseModel):
    """Confirm, correct or reject. A correction needs a value and a reason; a rejection a reason."""

    action: Literal["confirm", "correct", "reject"]
    value: str | None = None
    reason: str | None = Field(default=None, max_length=1000)
    expected_version: int

    @model_validator(mode="after")
    def _required_parts(self) -> Self:
        if self.action == "correct" and not (self.value and self.value.strip()):
            raise ValueError("value is required when action is correct")
        if self.action in {"correct", "reject"} and not (self.reason and self.reason.strip()):
            raise ValueError("reason is required when action is correct or reject")
        return self


class TypeChangeIn(BaseModel):
    doc_type: DocumentType
    reason: str | None = Field(default=None, max_length=500)


class TypeChangeAccepted(BaseModel):
    """202 body of setDocumentType: the document, and the job that re-reads it."""

    document: DocumentSummaryOut
    job: JobOut


def field_evidence(
    document_id: uuid.UUID, refs: list[str], meta: dict[str, LineMeta]
) -> EvidenceOut | None:
    """Where a field was read: the first cited page, every cited line, and their union box."""
    known = [r for r in refs if r in meta]
    if not known:
        return None
    page = meta[known[0]].page
    box = union_box(m.bbox for r in known if (m := meta[r]).page == page and m.bbox)
    return EvidenceOut(
        document_id=document_id,
        page=page,
        line_ids=list(refs),
        bbox=BoundingBox(**box) if box else None,
    )


def field_from_row(
    row: FieldRow,
    document_id: uuid.UUID,
    open_flags: list[Flag],
    meta: dict[str, LineMeta],
) -> FieldOut:
    return FieldOut(
        name=row.name,
        value=row.normalized_value if row.normalized_value is not None else row.value,
        original_value=row.original_value,
        certainty=row.certainty,
        flags=[flag_from_row(f) for f in open_flags],
        evidence=field_evidence(document_id, row.line_refs, meta),
        review_status=row.review_status,
        reviewed_by=str(row.reviewed_by) if row.reviewed_by else None,
        reviewed_at=row.reviewed_at,
        review_reason=row.review_reason,
        version=row.version,
    )

"""Document response shapes, as in contracts/openapi.yaml.

The database uses the schema doc's names; the contract uses its own. These models are where
the two meet, so nothing else renames anything:

    documents.borrower            -> owner
    documents.doc_type_certainty  -> type_certainty
    documents.created_at          -> uploaded_at
    pages.page_no                 -> Evidence.page
    fields.line_refs              -> Evidence.line_ids

``s3_key`` (and ``sha256``, ``mime``, ``size_bytes``) are not in the contract's DocumentSummary,
so they are never sent. Flags have their own table from D3; until then ``flags`` is empty.

A document whose SHA-256 already appears earlier in the same case carries the warning flag
DI-W206 ("This file is already in the case."). The flag is worked out when the response is
built; nothing is stored.

Not built yet: the contract's ``Field`` shape. Which of ``fields.value`` and
``fields.normalized_value`` it reads is decided with the extraction endpoint.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from app.api.schemas.jobs import JobOut
from app.db.enums import Certainty, DocumentStatus, DocumentType
from app.db.models import Flag
from app.services.documents import DocumentView
from app.services.documents import UploadResult as UploadOutcome

LineRef = Annotated[str, StringConstraints(pattern=r"^p[0-9]+-L[0-9]+$")]


class BoundingBox(BaseModel):
    """Box on the page image, as fractions of page width and height (0 to 1)."""

    x0: float = Field(ge=0, le=1)
    y0: float = Field(ge=0, le=1)
    x1: float = Field(ge=0, le=1)
    y1: float = Field(ge=0, le=1)


class EvidenceOut(BaseModel):
    """Where a value came from on the page."""

    document_id: uuid.UUID
    page: int = Field(ge=1)
    line_ids: list[LineRef]
    bbox: BoundingBox | None = None

    @classmethod
    def from_refs(
        cls,
        *,
        document_id: uuid.UUID,
        page_no: int,
        line_refs: list[str],
        bbox: BoundingBox | None = None,
    ) -> EvidenceOut:
        return cls(document_id=document_id, page=page_no, line_ids=line_refs, bbox=bbox)


class FlagOut(BaseModel):
    code: str
    severity: Literal["error", "warning", "info"]
    message: str
    evidence: EvidenceOut | None = None


class DocumentSummaryOut(BaseModel):
    """Built from a ``Document`` row (``from_attributes``); the aliases map the database names."""

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: uuid.UUID
    case_id: uuid.UUID
    file_name: str
    declared_type: DocumentType | None = None
    doc_type: DocumentType | None = None
    type_certainty: Certainty | None = Field(default=None, validation_alias="doc_type_certainty")
    status: DocumentStatus
    page_count: int | None = None
    owner: str | None = Field(default=None, validation_alias="borrower")
    period_start: date | None = None
    period_end: date | None = None
    flags: list[FlagOut] = Field(default_factory=list)
    summary: str | None = None
    uploaded_at: datetime = Field(validation_alias="created_at")


DUPLICATE_FLAG = FlagOut(
    code="DI-W206", severity="warning", message="This file is already in the case."
)


def flag_from_row(flag: Flag) -> FlagOut:
    """A stored flag as the contract's Flag. Only the contract's evidence keys are sent."""
    evidence = flag.evidence or {}
    shown = (
        EvidenceOut(
            document_id=uuid.UUID(evidence["document_id"]),
            page=evidence["page"],
            line_ids=evidence["line_ids"],
            bbox=BoundingBox(**evidence["bbox"]) if evidence.get("bbox") else None,
        )
        if {"document_id", "page", "line_ids"} <= set(evidence)
        else None
    )
    return FlagOut(
        code=flag.code, severity=flag.severity.value, message=flag.message, evidence=shown
    )


def summary_from_view(view: DocumentView) -> DocumentSummaryOut:
    """The contract's DocumentSummary: stored open flags, plus DI-W206 if it duplicates a file."""
    summary = DocumentSummaryOut.model_validate(view.document)
    flags = [flag_from_row(f) for f in view.flags]
    if view.duplicate:
        flags.append(DUPLICATE_FLAG)
    return summary.model_copy(update={"flags": flags})


class DocumentList(BaseModel):
    items: list[DocumentSummaryOut]

    @classmethod
    def from_views(cls, views: list[DocumentView]) -> DocumentList:
        return cls(items=[summary_from_view(v) for v in views])


class UploadResult(BaseModel):
    """202 body of uploadDocuments: the new documents and the job that reads them."""

    documents: list[DocumentSummaryOut]
    job: JobOut

    @classmethod
    def from_outcome(cls, outcome: UploadOutcome) -> UploadResult:
        return cls(
            documents=[summary_from_view(v) for v in outcome.documents],
            job=JobOut.model_validate(outcome.job),
        )


class PageImageOut(BaseModel):
    """A short-lived link to one page image, and the image's size in pixels.

    Boxes in ``Evidence.bbox`` are fractions of this image (origin top left), so a viewer needs
    ``width`` and ``height`` to draw them. The link stops working at ``expires_at``; ask again.
    """

    page: int = Field(ge=1)
    url: str
    expires_at: datetime
    width: int = Field(gt=0)
    height: int = Field(gt=0)

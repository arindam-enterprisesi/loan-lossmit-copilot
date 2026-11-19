"""Uploaded documents, their pages and the numbered lines read from each page (CPS-01, CPS-08)."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.enums import Certainty, DocTypeSource, DocumentStatus, ReadBy
from app.db.models._common import created_at_column, enum_type, uuid_pk


class Document(Base):
    __tablename__ = "documents"
    __table_args__ = (
        sa.CheckConstraint("sha256 ~ '^[0-9a-f]{64}$'", name="sha256_hex"),
        sa.CheckConstraint("size_bytes >= 0", name="size_bytes_non_negative"),
        # Not unique: the FSD warns about a duplicate upload ("Keep it anyway?", DI-W206); it
        # never blocks one.
        sa.Index("ix_documents_case_id_sha256", "case_id", "sha256"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    case_id: Mapped[uuid.UUID] = mapped_column(sa.ForeignKey("cases.id", ondelete="CASCADE"))
    # Names are stored but never sent to a model.
    file_name: Mapped[str] = mapped_column(sa.Text)
    # Relative to S3_PREFIX: app.storage.Storage adds the prefix. Never exposed by the API.
    s3_key: Mapped[str] = mapped_column(sa.Text)
    sha256: Mapped[str] = mapped_column(sa.String(64))
    mime: Mapped[str] = mapped_column(sa.String(100))
    size_bytes: Mapped[int] = mapped_column(sa.BigInteger)
    page_count: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)
    # Plain text, no CHECK: document types are administrator-managed configuration.
    # NULL declared_type means "auto-detect".
    declared_type: Mapped[str | None] = mapped_column(sa.String(64), nullable=True)
    doc_type: Mapped[str | None] = mapped_column(sa.String(64), nullable=True)
    doc_type_certainty: Mapped[Certainty | None] = mapped_column(
        enum_type(Certainty, "doc_type_certainty"), nullable=True
    )
    # Who decided doc_type; NULL until it has been classified.
    doc_type_source: Mapped[DocTypeSource | None] = mapped_column(
        enum_type(DocTypeSource, "doc_type_source"), nullable=True
    )
    status: Mapped[DocumentStatus] = mapped_column(
        enum_type(DocumentStatus, "status"),
        default=DocumentStatus.UPLOADED,
        server_default=DocumentStatus.UPLOADED.value,
    )
    # Filled from the extracted fields for the case overview. The API calls it `owner`.
    borrower: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    period_start: Mapped[date | None] = mapped_column(sa.Date, nullable=True)
    period_end: Mapped[date | None] = mapped_column(sa.Date, nullable=True)
    summary: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    created_at: Mapped[datetime] = created_at_column()


class Page(Base):
    __tablename__ = "pages"
    __table_args__ = (
        sa.UniqueConstraint("document_id", "page_no", name="uq_pages_document_id_page_no"),
        sa.CheckConstraint("page_no >= 1", name="page_no_positive"),
        sa.CheckConstraint("width > 0 AND height > 0", name="size_positive"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    document_id: Mapped[uuid.UUID] = mapped_column(
        sa.ForeignKey("documents.id", ondelete="CASCADE")
    )
    page_no: Mapped[int] = mapped_column(sa.Integer)
    # Relative to S3_PREFIX.
    image_s3_key: Mapped[str] = mapped_column(sa.Text)
    width: Mapped[int] = mapped_column(sa.Integer)
    height: Mapped[int] = mapped_column(sa.Integer)
    # NULL until the page has been read.
    read_by: Mapped[ReadBy | None] = mapped_column(enum_type(ReadBy, "read_by"), nullable=True)
    # The page number printed on the page itself, e.g. "Page 1 of 3" (it can disagree with page_no).
    printed_page_label: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    created_at: Mapped[datetime] = created_at_column()


class Line(Base):
    """One numbered line of OCR or text-layer text, with where it sits on the page.

    ``line_ref`` looks like ``p1-L31`` and is only unique within a document, so the
    pair ``(document_id, line_ref)`` is unique. Evidence elsewhere cites these refs.
    """

    __tablename__ = "lines"
    __table_args__ = (
        sa.UniqueConstraint("document_id", "line_ref", name="uq_lines_document_id_line_ref"),
        sa.CheckConstraint("line_ref ~ '^p[0-9]+-L[0-9]+$'", name="line_ref_format"),
        sa.CheckConstraint(
            "confidence IS NULL OR (confidence >= 0 AND confidence <= 1)", name="confidence_range"
        ),
        sa.Index("ix_lines_page_id", "page_id"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    document_id: Mapped[uuid.UUID] = mapped_column(
        sa.ForeignKey("documents.id", ondelete="CASCADE")
    )
    page_id: Mapped[uuid.UUID] = mapped_column(sa.ForeignKey("pages.id", ondelete="CASCADE"))
    line_ref: Mapped[str] = mapped_column(sa.Text)
    text: Mapped[str] = mapped_column(sa.Text)
    # Fractions of page width and height (0 to 1): {"x0": .., "y0": .., "x1": .., "y1": ..}
    bbox: Mapped[dict[str, Any]] = mapped_column(JSONB)
    # NULL for text-layer lines that have no OCR confidence.
    confidence: Mapped[float | None] = mapped_column(sa.Float, nullable=True)
    created_at: Mapped[datetime] = created_at_column()

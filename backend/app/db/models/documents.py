"""Uploaded documents, their pages and the numbered lines read from each page (CPS-01, CPS-08)."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.enums import Certainty, DocumentStatus
from app.db.models._common import created_at_column, enum_type, uuid_pk


class Document(Base):
    __tablename__ = "documents"
    __table_args__ = (
        sa.CheckConstraint("sha256 ~ '^[0-9a-f]{64}$'", name="sha256_hex"),
        # Not unique: the FSD warns about a duplicate upload ("Keep it anyway?"); it never blocks.
        sa.Index("ix_documents_case_id_sha256", "case_id", "sha256"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    case_id: Mapped[uuid.UUID] = mapped_column(sa.ForeignKey("cases.id", ondelete="CASCADE"))
    # Names are stored but never sent to a model.
    file_name: Mapped[str] = mapped_column(sa.Text)
    # Relative to S3_PREFIX: app.storage.Storage adds the prefix.
    file_key: Mapped[str] = mapped_column(sa.Text)
    sha256: Mapped[str] = mapped_column(sa.String(64))
    mime: Mapped[str] = mapped_column(sa.String(100))
    page_count: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)
    # Plain text, no CHECK: document types are administrator-managed configuration.
    # NULL declared_type means "auto-detect".
    declared_type: Mapped[str | None] = mapped_column(sa.String(64), nullable=True)
    doc_type: Mapped[str | None] = mapped_column(sa.String(64), nullable=True)
    doc_type_certainty: Mapped[Certainty | None] = mapped_column(
        enum_type(Certainty, "doc_type_certainty"), nullable=True
    )
    status: Mapped[DocumentStatus] = mapped_column(
        enum_type(DocumentStatus, "status"),
        default=DocumentStatus.UPLOADED,
        server_default=DocumentStatus.UPLOADED.value,
    )
    # Filled from the extracted fields for the case overview.
    owner: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    period_start: Mapped[date | None] = mapped_column(sa.Date, nullable=True)
    period_end: Mapped[date | None] = mapped_column(sa.Date, nullable=True)
    summary: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    created_at: Mapped[datetime] = created_at_column()


class Page(Base):
    __tablename__ = "pages"
    __table_args__ = (
        sa.UniqueConstraint("document_id", "number", name="uq_pages_document_id_number"),
        sa.CheckConstraint("number >= 1", name="number_positive"),
        sa.CheckConstraint("width > 0 AND height > 0", name="size_positive"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    document_id: Mapped[uuid.UUID] = mapped_column(
        sa.ForeignKey("documents.id", ondelete="CASCADE")
    )
    number: Mapped[int] = mapped_column(sa.Integer)
    # Relative to S3_PREFIX.
    image_key: Mapped[str] = mapped_column(sa.Text)
    width: Mapped[int] = mapped_column(sa.Integer)
    height: Mapped[int] = mapped_column(sa.Integer)


class Line(Base):
    """One numbered line of OCR or text-layer text, with where it sits on the page.

    ``id`` looks like ``p1-L31`` and is only unique within a document, so the
    primary key is ``(document_id, id)``. Evidence elsewhere cites these IDs.
    """

    __tablename__ = "lines"
    __table_args__ = (
        sa.CheckConstraint("id ~ '^p[0-9]+-L[0-9]+$'", name="id_format"),
        sa.CheckConstraint(
            "confidence IS NULL OR (confidence >= 0 AND confidence <= 1)", name="confidence_range"
        ),
        sa.Index("ix_lines_page_id", "page_id"),
    )

    id: Mapped[str] = mapped_column(sa.Text, primary_key=True)
    document_id: Mapped[uuid.UUID] = mapped_column(
        sa.ForeignKey("documents.id", ondelete="CASCADE"), primary_key=True
    )
    page_id: Mapped[uuid.UUID] = mapped_column(sa.ForeignKey("pages.id", ondelete="CASCADE"))
    text: Mapped[str] = mapped_column(sa.Text)
    # Fractions of page width and height (0 to 1): {"x0": .., "y0": .., "x1": .., "y1": ..}
    bbox: Mapped[dict[str, Any]] = mapped_column(JSONB)
    # NULL for text-layer lines that have no OCR confidence.
    confidence: Mapped[float | None] = mapped_column(sa.Float, nullable=True)

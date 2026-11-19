"""Ingestion (CPS-01, CPS-08): read an uploaded file into pages and numbered lines.

Every line gets an ID such as ``p1-L31`` (page 1, line 31, counted top to bottom) and a box on
the page, as fractions of the page width and height. Other features cite these IDs as evidence.

The parsers (``parse_pdf``, ``parse_image``) are pure: bytes in, pages and lines out, nothing
stored. ``ingest_document`` puts the result in S3 and Postgres; ``app.services.pipeline`` runs it.

Document text is data. It is never logged here, and never leaves this module except into the
``lines`` table.
"""

from __future__ import annotations

import asyncio
import io
import logging
import uuid
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Protocol

import pdfplumber
import pypdfium2 as pdfium
import pypdfium2.raw as pdfium_raw
from PIL import Image, UnidentifiedImageError
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.enums import DocumentStatus, FlagStatus, ReadBy
from app.db.models import Document, Line, Page
from app.services import audit, flags
from app.services.doc_lines import printed_page_label
from app.services.document_config import get_validation_config
from app.services.storage_keys import page_image_key
from app.storage import ObjectNotFoundError, Storage

logger = logging.getLogger(__name__)

POINTS_PER_INCH = 72  # PDF page sizes are in points


# --- what a parse produces ------------------------------------------------------------------


@dataclass(frozen=True)
class BBox:
    """A box as fractions (0 to 1) of the page width and height, origin at the top left."""

    x0: float
    y0: float
    x1: float
    y1: float

    def as_json(self) -> dict[str, float]:
        return {"x0": self.x0, "y0": self.y0, "x1": self.x1, "y1": self.y1}


@dataclass(frozen=True)
class ParsedLine:
    text: str
    bbox: BBox
    confidence: float | None = None  # None for the text layer, which has no OCR confidence


@dataclass
class ParsedPage:
    page_no: int
    width: int  # pixels of the rendered image
    height: int
    png: bytes
    lines: list[ParsedLine] = field(default_factory=list)
    read_by: ReadBy | None = None  # None until the page has been read


@dataclass(frozen=True)
class ParsedDocument:
    pages: list[ParsedPage]


class IngestionError(Exception):
    """The file cannot be ingested. ``code`` is stable; ``reason`` is shown to the user."""

    code = "unreadable"
    reason = "the file cannot be read"


class PasswordProtectedError(IngestionError):
    code = "password_protected"
    reason = "the file is password protected"


class UnreadableFileError(IngestionError):
    code = "unreadable"
    reason = "the file cannot be read"


# --- OCR seam -------------------------------------------------------------------------------


@dataclass(frozen=True)
class OcrLine:
    text: str
    bbox: BBox
    confidence: float | None = None


class OcrAdapter(Protocol):
    """Reads a page image that has no text layer. Real OCR is plugged in here later."""

    @property
    def read_by(self) -> ReadBy:
        """What to record in ``pages.read_by`` for pages this adapter read."""
        ...

    def read_page(self, png: bytes, width: int, height: int) -> list[OcrLine]:
        """Lines in reading order. May raise ``NotImplementedError`` when OCR is unavailable."""
        ...


class NotImplementedOcr:
    """The default until OCR exists: every image-only page stays unread."""

    read_by = ReadBy.TESSERACT

    def read_page(self, png: bytes, width: int, height: int) -> list[OcrLine]:
        raise NotImplementedError("OCR is not implemented yet")


# --- parsers --------------------------------------------------------------------------------


def _png_bytes(image: Image.Image) -> bytes:
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def _fraction(value: float, size: float) -> float:
    if size <= 0:
        return 0.0
    return min(max(value / size, 0.0), 1.0)


def _text_layer(data: bytes, page_count: int) -> list[list[ParsedLine]]:
    """The text layer of each page, one line per row of text. Empty lists when there is none."""
    empty: list[list[ParsedLine]] = [[] for _ in range(page_count)]
    try:
        with pdfplumber.open(io.BytesIO(data)) as pdf:
            if len(pdf.pages) != page_count:
                return empty
            pages: list[list[ParsedLine]] = []
            for page in pdf.pages:
                width, height = float(page.width), float(page.height)
                lines: list[ParsedLine] = []
                for row in page.extract_text_lines(return_chars=False):
                    text = str(row["text"]).strip()
                    if not text:
                        continue
                    box = BBox(
                        _fraction(float(row["x0"]), width),
                        _fraction(float(row["top"]), height),
                        _fraction(float(row["x1"]), width),
                        _fraction(float(row["bottom"]), height),
                    )
                    lines.append(ParsedLine(text, box))
                pages.append(lines)
            return pages
    except Exception:
        # pdfminer raises many exception types on odd files. A file pdfium could open but
        # pdfplumber cannot is treated as having no text layer.
        logger.warning("text layer could not be read (%d pages)", page_count)
        return empty


def parse_pdf(data: bytes, dpi: int) -> ParsedDocument:
    """Open with pypdfium2, render every page to PNG at ``dpi``, read the text layer."""
    try:
        document = pdfium.PdfDocument(data)
    except pdfium.PdfiumError as exc:
        if exc.err_code == pdfium_raw.FPDF_ERR_PASSWORD:
            raise PasswordProtectedError() from exc
        raise UnreadableFileError() from exc

    pages: list[ParsedPage] = []
    try:
        if len(document) == 0:
            raise UnreadableFileError()
        for index in range(len(document)):
            try:
                image = document[index].render(scale=dpi / POINTS_PER_INCH).to_pil()
            except pdfium.PdfiumError as exc:
                raise UnreadableFileError() from exc
            pages.append(ParsedPage(index + 1, image.width, image.height, _png_bytes(image)))
    finally:
        document.close()

    for page, lines in zip(pages, _text_layer(data, len(pages)), strict=True):
        page.lines = lines
        page.read_by = ReadBy.TEXT_LAYER if lines else None
    return ParsedDocument(pages)


def parse_image(data: bytes) -> ParsedDocument:
    """A PNG or JPEG is one page with no text layer; it is re-encoded as PNG at its own size."""
    try:
        with Image.open(io.BytesIO(data)) as image:
            image.load()  # decode everything now, so a truncated file fails here
            rgb = image.convert("RGB")
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as exc:
        raise UnreadableFileError() from exc
    return ParsedDocument([ParsedPage(1, rgb.width, rgb.height, _png_bytes(rgb))])


def parse_file(data: bytes, mime: str, dpi: int) -> ParsedDocument:
    if mime == "application/pdf":
        return parse_pdf(data, dpi)
    return parse_image(data)


# --- storing the result ---------------------------------------------------------------------


@dataclass(frozen=True)
class IngestResult:
    document_id: uuid.UUID
    file_name: str
    ok: bool
    code: str | None = None
    reason: str | None = None
    page_count: int = 0
    line_count: int = 0


# Which flag explains each way ingestion can fail (FSD error codes): the file itself, or reading it.
FAILURE_FLAG = {
    "password_protected": "DI-E201",
    "unreadable": "DI-E201",
    "original_missing": "DI-E201",
    "ocr_unavailable": "DI-E301",
    "no_text": "DI-E301",
}
INGEST_FLAGS = ("DI-E201", "DI-E301")


def _pages_phrase(pages: Sequence[int]) -> str:
    if len(pages) == 1:
        return f"page {pages[0]} has"
    return "pages " + ", ".join(str(p) for p in pages) + " have"


async def _fail(
    session: AsyncSession, document: Document, code: str, reason: str, page_count: int = 0
) -> IngestResult:
    document.status = DocumentStatus.FAILED
    await session.flush()
    # The reason is also a document flag, so the case overview can show why a file failed.
    flag_code = FAILURE_FLAG.get(code, "DI-E201")
    severity, message = get_validation_config().flag(flag_code, reason=reason)
    await flags.raise_flag(
        session,
        case_id=document.case_id,
        entity_type="document",
        entity_id=document.id,
        code=flag_code,
        severity=severity,
        message=message,
    )
    await audit.record(
        session,
        actor_id=None,
        role="worker",
        action="document.ingest_failed",
        entity_type="document",
        entity_id=document.id,
        case_id=document.case_id,
        after={"reason_code": code, "reason": reason},
    )
    logger.info("ingest failed document=%s code=%s", document.id, code)
    return IngestResult(document.id, document.file_name, False, code, reason, page_count)


async def ingest_document(
    session: AsyncSession,
    storage: Storage,
    ocr: OcrAdapter,
    document_id: uuid.UUID,
    *,
    dpi: int,
) -> IngestResult:
    """Read one document into ``pages`` and ``lines``. Flushes; the caller commits.

    Safe to run again: the document's earlier pages and lines are replaced.
    """
    document = await session.get(Document, document_id)
    if document is None:
        raise LookupError(f"document {document_id} does not exist")
    document.status = DocumentStatus.PROCESSING
    await session.flush()

    try:
        original = await asyncio.to_thread(storage.get, document.s3_key)
        parsed = await asyncio.to_thread(parse_file, original, document.mime, dpi)
    except ObjectNotFoundError:
        return await _fail(session, document, "original_missing", "the stored file is missing")
    except IngestionError as exc:
        return await _fail(session, document, exc.code, exc.reason)

    # Pages with no text layer go to OCR. With the default adapter they stay unread.
    unavailable: list[int] = []
    empty: list[int] = []
    for page in parsed.pages:
        if page.lines:
            continue
        try:
            ocr_lines = await asyncio.to_thread(ocr.read_page, page.png, page.width, page.height)
        except NotImplementedError:
            unavailable.append(page.page_no)
            continue
        if not ocr_lines:
            empty.append(page.page_no)
            continue
        page.lines = [ParsedLine(o.text, o.bbox, o.confidence) for o in ocr_lines]
        page.read_by = ocr.read_by

    # Replace what an earlier run stored (lines go with their pages).
    await session.execute(
        delete(Page)
        .where(Page.document_id == document.id)
        .execution_options(synchronize_session=False)
    )
    line_count = 0
    for page in parsed.pages:
        key = page_image_key(document.case_id, document.id, page.page_no)
        await asyncio.to_thread(storage.put, key, page.png, "image/png")
        page_row = Page(
            document_id=document.id,
            page_no=page.page_no,
            image_s3_key=key,
            width=page.width,
            height=page.height,
            read_by=page.read_by,
            printed_page_label=printed_page_label(line.text for line in page.lines),
        )
        session.add(page_row)
        await session.flush()
        session.add_all(
            Line(
                document_id=document.id,
                page_id=page_row.id,
                line_ref=f"p{page.page_no}-L{n}",
                text=line.text,
                bbox=line.bbox.as_json(),
                confidence=line.confidence,
            )
            for n, line in enumerate(page.lines, start=1)
        )
        line_count += len(page.lines)
    document.page_count = len(parsed.pages)
    await session.flush()

    if unavailable or empty:
        if unavailable:
            reason = f"{_pages_phrase(unavailable)} no readable text and OCR is not available yet"
            return await _fail(session, document, "ocr_unavailable", reason, len(parsed.pages))
        return await _fail(
            session,
            document,
            "no_text",
            f"{_pages_phrase(empty)} no readable text",
            len(parsed.pages),
        )

    # An earlier failure is over: close its flag. The next stage (classify) sets the next status.
    await flags.close_flags(
        session,
        entity_type="document",
        entity_ids=[document.id],
        codes=INGEST_FLAGS,
        status=FlagStatus.RESOLVED,
        reason="read successfully",
    )
    await audit.record(
        session,
        actor_id=None,
        role="worker",
        action="document.ingested",
        entity_type="document",
        entity_id=document.id,
        case_id=document.case_id,
        after={"page_count": len(parsed.pages), "line_count": line_count},
    )
    logger.info(
        "ingested document=%s pages=%d lines=%d", document.id, len(parsed.pages), line_count
    )
    return IngestResult(
        document.id, document.file_name, True, page_count=len(parsed.pages), line_count=line_count
    )

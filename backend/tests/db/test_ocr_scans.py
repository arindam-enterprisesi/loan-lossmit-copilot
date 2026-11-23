"""The two degraded scans through the whole pipeline with the real Tesseract.

Skipped when the ``tesseract`` program is not installed (CI and the worker image have it). The scans
are made from Daniel's pay stub (a photograph, two pages, the second one blurrier) and a mortgage
statement (a small grey JPEG). OCR makes mistakes, so these tests do not demand perfect text. They
demand the rule that matters: a figure is either read correctly or someone is told. A misread
figure may not sit in the case looking certain (CLAUDE.md rule 2; FSD 4.3 and 4.4).

Tesseract's output varies a little between versions, so nothing here depends on exact text.
"""

from __future__ import annotations

import shutil
from typing import Any

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.services.document_config import get_validation_config
from app.services.extractor import ExtractionOutcome
from app.services.fake_reader import FakeClassifier, FakeExtractor
from app.services.ocr import TesseractOcr
from app.storage import Storage
from app.worker import process_documents
from tests.conftest import Rendered
from tests.db.test_documents_api import rows
from tests.db.test_ingest_worker import (
    DPI_200,
    PHOTO,
    SCAN_JPG,
    audit_of,
    document_row,
    job_row,
    seeded,  # noqa: F401  (autouse fixture)
    upload_files,
)

pytestmark = pytest.mark.skipif(
    shutil.which("tesseract") is None, reason="the tesseract program is not installed"
)

MIN_CONFIDENCE = float(get_validation_config().min_line_confidence)
# What the photographed stub prints (the stub has a built-in defect: net pay is printed 2,083.61).
PRINTED = {
    "gross_pay_current": "3,070.50",
    "total_deductions_current": "1,036.89",
    "net_pay_current": "2,083.61",
}


async def read_scan(
    path: str,
    client: httpx.AsyncClient,
    storage: Storage,
    factory: async_sessionmaker[AsyncSession],
    rendered: Rendered,
    extractor: Any = None,
) -> dict[str, Any]:
    """Upload the scan and run every stage, reading pages with the real Tesseract."""
    body = await upload_files(client, rendered, [path])
    await process_documents(
        {
            "storage": storage,
            "session_factory": factory,
            "ingestion_config": DPI_200,
            "ocr": TesseractOcr(DPI_200.ocr, DPI_200.ocr_scale),
            "classifier": FakeClassifier(),
            "extractor": extractor or FakeExtractor(),
        },
        body["job"]["id"],
        [d["id"] for d in body["documents"]],
    )
    return body


async def fields_of(session: AsyncSession, document_id: str) -> list[Any]:
    """The active run's fields, each with the lowest OCR confidence among the lines it cites."""
    return await rows(
        session,
        "SELECT f.name, f.value, f.certainty, f.line_refs, "
        "(SELECT min(l.confidence) FROM lines l WHERE l.document_id = f.document_id "
        " AND l.line_ref = ANY(f.line_refs)) AS confidence "
        "FROM fields f JOIN extraction_runs r ON r.id = f.run_id AND r.active "
        "WHERE f.document_id = :d ORDER BY f.name",
        d=document_id,
    )


async def flag_codes(session: AsyncSession, document_id: str) -> set[str]:
    found = await rows(
        session,
        "SELECT DISTINCT code FROM flags WHERE case_id = "
        "(SELECT case_id FROM documents WHERE id = :d)",
        d=document_id,
    )
    return {r.code for r in found}


def plain(value: str | None) -> str | None:
    return value.replace(" ", "") if value else value


async def test_the_photographed_stub_is_read_with_confidence_and_boxes(
    docs_client: httpx.AsyncClient,
    session: AsyncSession,
    s3_storage: Storage,
    session_factory: async_sessionmaker[AsyncSession],
    rendered: Rendered,
) -> None:
    body = await read_scan(PHOTO, docs_client, s3_storage, session_factory, rendered)
    [doc] = body["documents"]

    assert (await job_row(session, body)).status == "succeeded"
    pages = await rows(
        session,
        "SELECT page_no, read_by, "
        "(SELECT count(*) FROM lines l WHERE l.page_id = p.id) AS n FROM pages p "
        "WHERE p.document_id = :d ORDER BY page_no",
        d=doc["id"],
    )
    assert [(p.page_no, p.read_by) for p in pages] == [(1, "tesseract"), (2, "tesseract")]
    assert pages[0].n >= 20  # the first page is a clear photograph of a full pay stub
    lines = await rows(
        session,
        "SELECT line_ref, text, bbox, confidence FROM lines WHERE document_id = :d",
        d=doc["id"],
    )
    for line in lines:
        assert 0 < line.confidence <= 1 and line.text.strip()
        box = line.bbox
        assert 0 <= box["x0"] < box["x1"] <= 1 and 0 <= box["y0"] < box["y1"] <= 1
    # The engine that read the pages is on record.
    [event] = await audit_of(session, "document.ingested")
    assert event.after["ocr"]["engine"] == "tesseract" and event.after["ocr"]["pages"] == [1, 2]
    assert event.after["ocr"]["version"][0].isdigit()


async def test_every_key_amount_of_the_photographed_stub_is_read_or_flagged(
    docs_client: httpx.AsyncClient,
    session: AsyncSession,
    s3_storage: Storage,
    session_factory: async_sessionmaker[AsyncSession],
    rendered: Rendered,
) -> None:
    body = await read_scan(PHOTO, docs_client, s3_storage, session_factory, rendered)
    [doc] = body["documents"]

    fields = {f.name: f for f in await fields_of(session, doc["id"])}
    codes = await flag_codes(session, doc["id"])

    assert (await document_row(session, doc["id"])).status == "needs_review"
    # The lines that are clearly readable give the dates.
    assert fields["pay_date"].value == "2026-10-02"
    for name, printed in PRINTED.items():
        found = fields.get(name)
        read_right = found is not None and plain(found.value) == printed
        not_found = found is None or found.value is None
        # Right, or not found (and then it says so), or different (and then it is not
        # trusted: the arithmetic checks object, or it was read from lines OCR was unsure of).
        if read_right:
            continue
        if not_found:
            assert "DI-W604" in codes, f"{name} is missing and nothing says so"
        else:
            assert found is not None
            unsure = found.certainty != "high"
            assert unsure or {"DI-CHK-01", "DI-CHK-02"} & codes, f"{name} was misread silently"


async def test_a_value_read_from_a_line_ocr_was_unsure_of_is_never_certain(
    docs_client: httpx.AsyncClient,
    session: AsyncSession,
    s3_storage: Storage,
    session_factory: async_sessionmaker[AsyncSession],
    rendered: Rendered,
) -> None:
    # FSD 4.4: a cited line read below the minimum confidence lowers the field's certainty, so the
    # reviewer sees it first. Checked here on real OCR output, not on made-up confidences.
    body = await read_scan(PHOTO, docs_client, s3_storage, session_factory, rendered)
    [doc] = body["documents"]

    fields = await fields_of(session, doc["id"])
    unsure_lines = await rows(
        session,
        "SELECT line_ref FROM lines WHERE document_id = :d AND confidence < :m",
        d=doc["id"],
        m=MIN_CONFIDENCE,
    )

    assert unsure_lines, "the blurred photograph must have lines OCR was unsure of"
    unsure = [f for f in fields if f.confidence is not None and f.confidence < MIN_CONFIDENCE]
    assert [f.name for f in unsure if f.certainty == "high"] == []


class ReadsNothing:
    """A reader that gets no field out of the page: what is left when OCR could not read it.

    The rule-based reader now reads a mortgage statement's printed lines, so on this scan it could
    pick up a stray line from the noise; this test is about what the pipeline says when nothing
    usable comes out, so the reader is told to find nothing.
    """

    async def extract(self, doc_type: str, lines: Any) -> ExtractionOutcome:
        return ExtractionOutcome({}, [], "fake", "reads-nothing", "fake-extract@1")


async def test_a_scan_ocr_cannot_read_does_not_look_read(
    docs_client: httpx.AsyncClient,
    session: AsyncSession,
    s3_storage: Storage,
    session_factory: async_sessionmaker[AsyncSession],
    rendered: Rendered,
) -> None:
    body = await read_scan(
        SCAN_JPG, docs_client, s3_storage, session_factory, rendered, extractor=ReadsNothing()
    )
    [doc] = body["documents"]

    job = await job_row(session, body)
    status = (await document_row(session, doc["id"])).status
    fields = await fields_of(session, doc["id"])
    codes = await flag_codes(session, doc["id"])

    assert job.progress == 1.0 and job.status in {"succeeded", "failed"}  # it ended, no crash
    assert status in {"needs_review", "failed"}  # never "reviewed"
    assert [f.name for f in fields if f.certainty == "high"] == []  # nothing it read is trusted
    # And someone is told: nothing was found, or the page could not be read at all.
    assert {"DI-W604", "DI-E301", "DI-E401"} & codes

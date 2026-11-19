"""The background job that reads uploaded files into pages and numbered lines.

Each test uploads through the API (so the rows, S3 objects and job are the real ones) and then
runs the real ``process_documents`` worker function, stopped after the ingest stage (the
pipeline tests cover the later stages), against Postgres and a moto S3.
"""

from __future__ import annotations

import io
import uuid
from typing import Any

import httpx
import pytest
from PIL import Image
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.enums import ReadBy
from app.db.seed import case_id, seed
from app.services.document_config import get_document_fields, get_validation_config
from app.services.fake_reader import FakeClassifier, FakeExtractor
from app.services.ingestion import BBox, NotImplementedOcr, OcrLine
from app.services.ingestion_config import IngestionConfig
from app.services.pipeline import Readers, run_pipeline_job
from app.storage import Storage, StorageError
from app.worker import process_documents
from tests.conftest import Rendered
from tests.data.helpers import read_pages
from tests.db.conftest import S3_PREFIX, s3_object
from tests.db.test_documents_api import AUGUST, STUB, rows, upload

DANIEL = case_id("Daniel Reyes — purchase")
LOCKED = "broken/locked_w2_2025.pdf"
CORRUPT = "broken/corrupt_bank_statement.pdf"
PHOTO = "broken/scan_pay_stub_photo.pdf"
SCAN_JPG = "broken/scan_mortgage_statement.jpg"
# Full resolution where the size matters; a small one for the tests that read every file.
DPI_200 = IngestionConfig(version="t", label="illustrative", max_file_mb=25, render_dpi=200)
DPI_50 = IngestionConfig(version="t", label="illustrative", max_file_mb=25, render_dpi=50)
NO_OCR = "no readable text and OCR is not available yet"


@pytest.fixture(autouse=True)
async def seeded(session: AsyncSession) -> None:
    await seed(session, "demo-pass")


def upload_name(path: str) -> str:
    return path.replace("/", "__")


async def upload_files(
    client: httpx.AsyncClient, rendered: Rendered, paths: list[str]
) -> dict[str, Any]:
    response = await upload(client, DANIEL, [(upload_name(p), rendered.read(p)) for p in paths])
    assert response.status_code == 202, response.text
    return response.json()


async def run_job(
    body: dict[str, Any],
    storage: Storage,
    factory: async_sessionmaker[AsyncSession],
    *,
    config: IngestionConfig = DPI_50,
    **ctx: Any,
) -> None:
    await process_documents(
        {"storage": storage, "session_factory": factory, "ingestion_config": config, **ctx},
        body["job"]["id"],
        [d["id"] for d in body["documents"]],
        ["ingest"],  # these tests are about ingestion; the pipeline tests run every stage
    )


async def job_row(session: AsyncSession, body: dict[str, Any]) -> Any:
    [row] = await rows(
        session,
        "SELECT status, stage, progress, error, attempts FROM jobs WHERE id = :j",
        j=body["job"]["id"],
    )
    return row


async def document_row(session: AsyncSession, document_id: str) -> Any:
    [row] = await rows(
        session, "SELECT status, page_count FROM documents WHERE id = :d", d=document_id
    )
    return row


async def lines_of(session: AsyncSession, document_id: str) -> list[tuple[str, str]]:
    result = await rows(
        session,
        "SELECT l.line_ref, l.text FROM lines l JOIN pages p ON p.id = l.page_id "
        "WHERE l.document_id = :d "
        "ORDER BY p.page_no, CAST(substr(l.line_ref, strpos(l.line_ref, 'L') + 1) AS integer)",
        d=document_id,
    )
    return [(r.line_ref, r.text) for r in result]


async def audit_of(session: AsyncSession, action: str) -> list[Any]:
    return await rows(
        session,
        "SELECT actor_id, role, entity_type, entity_id, case_id, after FROM audit_events "
        "WHERE action = :a ORDER BY id",
        a=action,
    )


# --- documents that read well ---------------------------------------------------------------


async def test_a_pay_stub_is_read_into_pages_lines_and_images(
    docs_client: httpx.AsyncClient,
    session: AsyncSession,
    s3_storage: Storage,
    session_factory: async_sessionmaker[AsyncSession],
    rendered: Rendered,
) -> None:
    body = await upload_files(docs_client, rendered, [STUB])
    [doc] = body["documents"]

    await run_job(body, s3_storage, session_factory, config=DPI_200)

    job = await job_row(session, body)
    assert (job.status, job.stage, job.progress, job.error, job.attempts) == (
        "succeeded",
        "ingest",
        1.0,
        None,
        1,
    )
    assert tuple(await document_row(session, doc["id"])) == ("processing", 2)

    pages = await rows(
        session,
        "SELECT page_no, image_s3_key, width, height, read_by FROM pages "
        "WHERE document_id = :d ORDER BY page_no",
        d=doc["id"],
    )
    assert [tuple(p) for p in pages] == [
        (n, f"cases/{DANIEL}/documents/{doc['id']}/pages/{n}.png", 1700, 2200, "text_layer")
        for n in (1, 2)
    ]
    for page in pages:  # the 200 DPI page images are in S3 and decode at the right size
        stored = s3_object(f"{S3_PREFIX}{page.image_s3_key}")
        assert stored["content_type"] == "image/png"
        with Image.open(io.BytesIO(stored["body"])) as image:
            assert image.size == (1700, 2200)

    lines = await lines_of(session, doc["id"])
    assert lines == [
        (f"p{p}-L{n}", text)
        for p, page_lines in enumerate(read_pages(rendered.path(STUB)), start=1)
        for n, text in enumerate(page_lines, start=1)
    ]
    assert "2,083.61" in dict(lines)["p1-L31"]  # the printed net pay the arithmetic check catches

    [line] = await rows(
        session,
        "SELECT bbox, confidence FROM lines WHERE document_id = :d AND line_ref = 'p1-L1'",
        d=doc["id"],
    )
    assert set(line.bbox) == {"x0", "y0", "x1", "y1"}
    assert all(0 <= v <= 1 for v in line.bbox.values()) and line.confidence is None

    [event] = await audit_of(session, "document.ingested")
    assert (event.actor_id, event.role, event.entity_type) == (None, "worker", "document")
    assert event.entity_id == uuid.UUID(doc["id"]) and event.case_id == DANIEL
    assert event.after == {"page_count": 2, "line_count": len(lines)}


async def test_every_case_file_is_read_to_exactly_the_rows_that_were_drawn(
    docs_client: httpx.AsyncClient,
    session: AsyncSession,
    s3_storage: Storage,
    session_factory: async_sessionmaker[AsyncSession],
    rendered: Rendered,
) -> None:
    paths = [
        f["path"]
        for f in rendered.manifest["files"]
        if f["role"] in {"case", "withheld"} and f["path"].endswith(".pdf")
    ]
    assert len(paths) == 17
    body = await upload_files(docs_client, rendered, paths)

    await run_job(body, s3_storage, session_factory)

    job = await job_row(session, body)
    assert (job.status, job.progress, job.error) == ("succeeded", 1.0, None)
    for path, doc in zip(paths, body["documents"], strict=True):
        expected = read_pages(rendered.path(path))
        assert tuple(await document_row(session, doc["id"])) == ("processing", len(expected)), path
        assert await lines_of(session, doc["id"]) == [
            (f"p{p}-L{n}", text)
            for p, page_lines in enumerate(expected, start=1)
            for n, text in enumerate(page_lines, start=1)
        ], path
    assert len(await audit_of(session, "document.ingested")) == 17


async def test_running_a_job_again_replaces_the_pages_and_lines(
    docs_client: httpx.AsyncClient,
    session: AsyncSession,
    s3_storage: Storage,
    session_factory: async_sessionmaker[AsyncSession],
    rendered: Rendered,
) -> None:
    body = await upload_files(docs_client, rendered, [STUB])
    [doc] = body["documents"]
    await run_job(body, s3_storage, session_factory)
    first = await lines_of(session, doc["id"])

    await run_job(body, s3_storage, session_factory)

    assert await lines_of(session, doc["id"]) == first
    [pages] = await rows(
        session, "SELECT count(*) AS n FROM pages WHERE document_id = :d", d=doc["id"]
    )
    assert pages.n == 2
    job = await job_row(session, body)
    assert (job.status, job.attempts) == ("succeeded", 2)


# --- the broken set -------------------------------------------------------------------------


async def test_unreadable_files_fail_with_a_reason_and_do_not_stop_the_rest(
    docs_client: httpx.AsyncClient,
    session: AsyncSession,
    s3_storage: Storage,
    session_factory: async_sessionmaker[AsyncSession],
    rendered: Rendered,
) -> None:
    paths = [LOCKED, STUB, CORRUPT, PHOTO, SCAN_JPG]
    body = await upload_files(docs_client, rendered, paths)
    docs = dict(zip(paths, (d["id"] for d in body["documents"]), strict=True))

    await run_job(body, s3_storage, session_factory)

    job = await job_row(session, body)
    assert job.status == "failed" and job.progress == 1.0 and job.stage == "ingest"
    assert job.error == (
        "We couldn't use broken__locked_w2_2025.pdf: the file is password protected. "
        "We couldn't use broken__corrupt_bank_statement.pdf: the file cannot be read. "
        f"We couldn't use broken__scan_pay_stub_photo.pdf: pages 1, 2 have {NO_OCR}. "
        f"We couldn't use broken__scan_mortgage_statement.jpg: page 1 has {NO_OCR}."
    )
    statuses = {p: (await document_row(session, d)).status for p, d in docs.items()}
    assert statuses == {
        LOCKED: "failed",
        STUB: "processing",  # the good file in the same upload was read
        CORRUPT: "failed",
        PHOTO: "failed",
        SCAN_JPG: "failed",
    }
    assert len(await lines_of(session, docs[STUB])) > 0

    async def pages_and_lines(path: str) -> tuple[int, int]:
        [p] = await rows(
            session, "SELECT count(*) AS n FROM pages WHERE document_id = :d", d=docs[path]
        )
        return p.n, len(await lines_of(session, docs[path]))

    assert await pages_and_lines(LOCKED) == (0, 0)
    assert await pages_and_lines(CORRUPT) == (0, 0)
    # The scans keep their page images (a reviewer can still look at them) but have no lines.
    assert await pages_and_lines(PHOTO) == (2, 0)
    assert await pages_and_lines(SCAN_JPG) == (1, 0)
    read_by = await rows(
        session, "SELECT DISTINCT read_by FROM pages WHERE document_id = :d", d=docs[PHOTO]
    )
    assert [r.read_by for r in read_by] == [None]

    failed = {e.entity_id: e.after for e in await audit_of(session, "document.ingest_failed")}
    assert {k: v["reason_code"] for k, v in failed.items()} == {
        uuid.UUID(docs[LOCKED]): "password_protected",
        uuid.UUID(docs[CORRUPT]): "unreadable",
        uuid.UUID(docs[PHOTO]): "ocr_unavailable",
        uuid.UUID(docs[SCAN_JPG]): "ocr_unavailable",
    }
    assert failed[uuid.UUID(docs[LOCKED])]["reason"] == "the file is password protected"
    assert len(await audit_of(session, "document.ingested")) == 1


async def test_a_missing_original_fails_the_document(
    docs_client: httpx.AsyncClient,
    session: AsyncSession,
    s3_storage: Storage,
    session_factory: async_sessionmaker[AsyncSession],
    rendered: Rendered,
) -> None:
    body = await upload_files(docs_client, rendered, [STUB])
    [doc] = body["documents"]
    s3_storage.delete(f"cases/{DANIEL}/documents/{doc['id']}/original")

    await run_job(body, s3_storage, session_factory)

    assert (await document_row(session, doc["id"])).status == "failed"
    job = await job_row(session, body)
    assert job.status == "failed" and "the stored file is missing" in job.error


async def test_an_unexpected_error_fails_the_job_and_is_raised(
    docs_client: httpx.AsyncClient,
    session: AsyncSession,
    s3_storage: Storage,
    session_factory: async_sessionmaker[AsyncSession],
    rendered: Rendered,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    body = await upload_files(docs_client, rendered, [STUB])
    [doc] = body["documents"]

    def broken_get(key: str) -> bytes:
        raise StorageError("get failed: InternalError")

    monkeypatch.setattr(s3_storage, "get", broken_get)

    with pytest.raises(StorageError):
        await run_job(body, s3_storage, session_factory)

    job = await job_row(session, body)
    assert (job.status, job.error) == ("failed", "Reading the files stopped unexpectedly.")
    # The crash is recorded where the user can see it, and they can re-run that stage (DI-E801).
    assert (await document_row(session, doc["id"])).status == "failed"
    [crash] = await rows(
        session,
        "SELECT code, severity, message FROM flags WHERE entity_id = :d",
        d=doc["id"],
    )
    assert tuple(crash) == (
        "DI-E801",
        "error",
        "Processing stopped at ingest. You can re-run this stage.",
    )


async def test_a_job_that_does_not_exist_is_an_error(
    s3_storage: Storage, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    readers = Readers(
        storage=s3_storage,
        ocr=NotImplementedOcr(),
        classifier=FakeClassifier(),
        extractor=FakeExtractor(),
        dpi=50,
        rules=get_validation_config(),
        cfg=get_document_fields(),
    )
    with pytest.raises(LookupError):
        await run_pipeline_job(session_factory, readers, uuid.uuid4(), [uuid.uuid4()])


# --- the OCR seam ---------------------------------------------------------------------------


class FakeOcr:
    """Stands in for a real OCR engine: two lines for any page it is given."""

    read_by = ReadBy.TESSERACT

    def __init__(self, lines: list[OcrLine] | None = None) -> None:
        self.lines = (
            lines
            if lines is not None
            else [
                OcrLine("Net pay 2,033.61", BBox(0.10, 0.20, 0.50, 0.25), 0.91),
                OcrLine("Gross 3,070.50", BBox(0.10, 0.30, 0.50, 0.35), 0.80),
            ]
        )
        self.calls: list[tuple[bytes, int, int]] = []

    def read_page(self, png: bytes, width: int, height: int) -> list[OcrLine]:
        self.calls.append((png, width, height))
        return self.lines


async def test_pages_without_a_text_layer_go_to_the_ocr_adapter(
    docs_client: httpx.AsyncClient,
    session: AsyncSession,
    s3_storage: Storage,
    session_factory: async_sessionmaker[AsyncSession],
    rendered: Rendered,
) -> None:
    body = await upload_files(docs_client, rendered, [PHOTO])
    [doc] = body["documents"]
    ocr = FakeOcr()

    await run_job(body, s3_storage, session_factory, config=DPI_200, ocr=ocr)

    assert (await job_row(session, body)).status == "succeeded"
    assert tuple(await document_row(session, doc["id"])) == ("processing", 2)
    assert len(ocr.calls) == 2  # one call per image-only page
    for png, width, height in ocr.calls:
        assert png.startswith(b"\x89PNG") and (width, height) == (1700, 2200)
    assert await lines_of(session, doc["id"]) == [
        ("p1-L1", "Net pay 2,033.61"),
        ("p1-L2", "Gross 3,070.50"),
        ("p2-L1", "Net pay 2,033.61"),
        ("p2-L2", "Gross 3,070.50"),
    ]
    read_by = await rows(
        session, "SELECT DISTINCT read_by FROM pages WHERE document_id = :d", d=doc["id"]
    )
    assert [r.read_by for r in read_by] == ["tesseract"]
    [first] = await rows(
        session,
        "SELECT bbox, confidence FROM lines WHERE document_id = :d AND line_ref = 'p1-L1'",
        d=doc["id"],
    )
    assert first.confidence == pytest.approx(0.91)
    assert first.bbox == {"x0": 0.1, "y0": 0.2, "x1": 0.5, "y1": 0.25}


async def test_a_page_with_a_text_layer_never_reaches_the_ocr_adapter(
    docs_client: httpx.AsyncClient,
    s3_storage: Storage,
    session_factory: async_sessionmaker[AsyncSession],
    rendered: Rendered,
) -> None:
    body = await upload_files(docs_client, rendered, [STUB, AUGUST])
    ocr = FakeOcr()
    await run_job(body, s3_storage, session_factory, ocr=ocr)
    assert ocr.calls == []


async def test_an_ocr_engine_that_finds_no_text_fails_the_page(
    docs_client: httpx.AsyncClient,
    session: AsyncSession,
    s3_storage: Storage,
    session_factory: async_sessionmaker[AsyncSession],
    rendered: Rendered,
) -> None:
    body = await upload_files(docs_client, rendered, [SCAN_JPG])
    [doc] = body["documents"]

    await run_job(body, s3_storage, session_factory, ocr=FakeOcr(lines=[]))

    assert (await document_row(session, doc["id"])).status == "failed"
    job = await job_row(session, body)
    assert (
        job.error
        == "We couldn't use broken__scan_mortgage_statement.jpg: page 1 has no readable text."
    )
    [event] = await audit_of(session, "document.ingest_failed")
    assert event.after["reason_code"] == "no_text"

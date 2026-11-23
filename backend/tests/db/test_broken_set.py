"""The whole broken set through the API and the worker: every failure explained, nothing crashes.

``data/synthetic/rendered/broken`` holds the files a real upload will bring: a password-protected
PDF, a corrupt PDF, a CSV (not an accepted type), a duplicate of a good file and two degraded
scans. Here they go in with a good file, through the whole pipeline, with OCR switched off (the
state of a machine without Tesseract), and each failure must end as a document marked ``failed``
with a flag whose message is the one in the error catalog (``backend/config/validation.yaml``:
DI-E201 for a file that cannot be used, DI-E301 for one that cannot be read). One bad file never
stops the others, and running the job again is harmless.

With Tesseract the scans are read instead (see ``test_ocr_scans.py``); this test is about what
happens when they cannot be.
"""

from __future__ import annotations

from typing import Any

import httpx
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.enums import Role
from app.services.ingestion import NotImplementedOcr
from app.storage import Storage
from tests.conftest import Rendered
from tests.db.conftest import auth_headers
from tests.db.test_documents_api import DANIEL, DUPLICATE_FLAG, STUB, counts, s3_keys, upload
from tests.db.test_documents_api import seeded as seeded  # autouse fixture
from tests.db.test_pipeline import document, flags_of, one, run

NO_OCR = "no readable text and OCR is not available yet"
UPLOAD = [
    ("good_stub.pdf", STUB),
    ("duplicate_pay_stub.pdf", "broken/duplicate_pay_stub.pdf"),
    ("locked.pdf", "broken/locked_w2_2025.pdf"),
    ("corrupt.pdf", "broken/corrupt_bank_statement.pdf"),
    ("scan_photo.pdf", "broken/scan_pay_stub_photo.pdf"),
    ("scan.jpg", "broken/scan_mortgage_statement.jpg"),
]
# file -> (flag code, the catalog's message with the reason filled in)
FAILURES = {
    "locked.pdf": ("DI-E201", "We couldn't use this file: the file is password protected."),
    "corrupt.pdf": ("DI-E201", "We couldn't use this file: the file cannot be read."),
    "scan_photo.pdf": ("DI-E301", f"We couldn't read this document: pages 1, 2 have {NO_OCR}."),
    "scan.jpg": ("DI-E301", f"We couldn't read this document: page 1 has {NO_OCR}."),
}


async def upload_the_set(
    client: httpx.AsyncClient, rendered: Rendered
) -> tuple[dict[str, Any], dict[str, str]]:
    response = await upload(client, DANIEL, [(name, rendered.read(path)) for name, path in UPLOAD])
    assert response.status_code == 202, response.text
    body = response.json()
    return body, {d["file_name"]: d["id"] for d in body["documents"]}


async def test_every_broken_file_ends_failed_with_the_catalogs_message_and_the_rest_is_read(
    docs_client: httpx.AsyncClient,
    session: AsyncSession,
    s3_storage: Storage,
    session_factory: async_sessionmaker[AsyncSession],
    rendered: Rendered,
) -> None:
    body, ids = await upload_the_set(docs_client, rendered)

    await run(body, s3_storage, session_factory, ocr=NotImplementedOcr())  # must not raise

    job = await one(session, "SELECT status, stage, progress, error FROM jobs")
    assert (job.status, job.progress) == ("failed", 1.0)
    assert job.error == (
        "We couldn't use locked.pdf: the file is password protected. "
        "We couldn't use corrupt.pdf: the file cannot be read. "
        f"We couldn't use scan_photo.pdf: pages 1, 2 have {NO_OCR}. "
        f"We couldn't use scan.jpg: page 1 has {NO_OCR}."
    )
    # The good file and the duplicate of it were read as usual.
    for name in ("good_stub.pdf", "duplicate_pay_stub.pdf"):
        assert (await document(session, ids[name])).status == "needs_review"
    # Each broken file failed, with one error flag whose message comes from the catalog.
    for name, (code, message) in FAILURES.items():
        assert (await document(session, ids[name])).status == "failed", name
        errors = [f for f in await flags_of(session, ids[name]) if f.severity == "error"]
        assert [(f.code, f.message) for f in errors] == [(code, message)], name
    # The same messages are what the case overview shows.
    listed = (await docs_client.get(f"/api/v1/cases/{DANIEL}/documents", headers=headers())).json()
    shown = {d["file_name"]: d["flags"] for d in listed["items"]}
    for name, (code, message) in FAILURES.items():
        assert [(f["code"], f["severity"], f["message"]) for f in shown[name]] == [
            (code, "error", message)
        ], name
    # And the duplicate carries its warning (FSD DI-W206: kept, never refused).
    assert DUPLICATE_FLAG in shown["duplicate_pay_stub.pdf"]


async def test_running_the_job_again_is_harmless(
    docs_client: httpx.AsyncClient,
    session: AsyncSession,
    s3_storage: Storage,
    session_factory: async_sessionmaker[AsyncSession],
    rendered: Rendered,
) -> None:
    body, ids = await upload_the_set(docs_client, rendered)
    await run(body, s3_storage, session_factory, ocr=NotImplementedOcr())

    await run(body, s3_storage, session_factory, ocr=NotImplementedOcr())  # a retry

    for name in FAILURES:
        assert (await document(session, ids[name])).status == "failed", name
        errors = [f for f in await flags_of(session, ids[name]) if f.severity == "error"]
        assert len(errors) == 1, name  # the flag is updated, never doubled
    assert (await document(session, ids["good_stub.pdf"])).status == "needs_review"
    job = await one(session, "SELECT status, attempts FROM jobs")
    assert (job.status, job.attempts) == ("failed", 2)


async def test_a_file_of_an_unsupported_type_is_refused_before_anything_is_stored(
    docs_client: httpx.AsyncClient,
    session: AsyncSession,
    s3_storage: Storage,
    rendered: Rendered,
) -> None:
    response = await upload(
        docs_client, DANIEL, [("export.csv", rendered.read("broken/bank_transactions_export.csv"))]
    )

    assert response.status_code == 415
    assert response.json() == {
        "code": "unsupported_media",
        "message": "We couldn't use export.csv: only PDF, PNG and JPEG files are accepted.",
        "details": {"file_name": "export.csv"},
    }
    assert s3_keys() == [] and await counts(session) == {
        "documents": 0,
        "jobs": 0,
        "audit_events": 0,
    }


def headers() -> dict[str, str]:
    return auth_headers(Role.UNDERWRITER)

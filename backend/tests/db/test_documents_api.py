"""POST and GET /api/v1/cases/{case_id}/documents: real Postgres, moto S3 and a fake queue."""

from __future__ import annotations

import hashlib
import uuid
from typing import Any

import httpx
import pytest
import sqlalchemy as sa
from botocore.exceptions import EndpointConnectionError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas.documents import DocumentSummaryOut
from app.db.enums import Role
from app.db.seed import case_id, seed, user_id
from app.main import app
from app.services.ingestion_config import get_ingestion_config
from app.storage import Storage, StorageError
from tests.conftest import Rendered
from tests.db.conftest import S3_PREFIX, FakeQueue, auth_headers, s3_keys, s3_object

PASSWORD = "demo-pass"
DANIEL = case_id("Daniel Reyes — purchase")  # underwriting
ANGELA = case_id("Angela Whitfield — hardship")  # loss_mitigation

STUB = "daniel_reyes/pay_stub_2026-09-27.pdf"
AUGUST = "daniel_reyes/bank_statement_2026-08.pdf"
SEPTEMBER = "daniel_reyes/bank_statement_2026-09.pdf"
CSV = "broken/bank_transactions_export.csv"
MIB = 1024 * 1024
DUPLICATE_FLAG = {
    "code": "DI-W206",
    "severity": "warning",
    "message": "This file is already in the case.",
    "evidence": None,
}


@pytest.fixture(autouse=True)
async def seeded(session: AsyncSession) -> None:
    await seed(session, PASSWORD)


async def upload(
    client: httpx.AsyncClient,
    case: uuid.UUID | str,
    files: list[tuple[str, bytes]],
    *,
    role: Role = Role.UNDERWRITER,
    declared_type: str | None = None,
) -> httpx.Response:
    return await client.post(
        f"/api/v1/cases/{case}/documents",
        files=[("files", (name, data, "application/octet-stream")) for name, data in files],
        data={"declared_type": declared_type} if declared_type else None,
        headers=auth_headers(role),
    )


async def rows(session: AsyncSession, sql: str, **params: Any) -> list[Any]:
    return list((await session.execute(sa.text(sql), params)).all())


async def counts(session: AsyncSession) -> dict[str, int]:
    return {
        table: (await session.scalar(sa.text(f"SELECT count(*) FROM {table}"))) or 0
        for table in ("documents", "jobs", "audit_events")
    }


# --- a successful upload --------------------------------------------------------------------


async def test_upload_one_pdf(
    docs_client: httpx.AsyncClient,
    session: AsyncSession,
    rendered: Rendered,
    fake_queue: FakeQueue,
) -> None:
    data = rendered.read(STUB)

    response = await upload(docs_client, DANIEL, [("pay_stub_2026-09-27.pdf", data)])

    assert response.status_code == 202
    body = response.json()
    assert set(body) == {"documents", "job"}
    [doc] = body["documents"]
    assert set(doc) == set(DocumentSummaryOut.model_fields)  # exactly the contract's fields
    assert doc["file_name"] == "pay_stub_2026-09-27.pdf" and doc["case_id"] == str(DANIEL)
    assert doc["status"] == "uploaded" and doc["flags"] == []
    assert [
        doc[k] for k in ("declared_type", "doc_type", "type_certainty", "owner", "page_count")
    ] == [None] * 5
    job = body["job"]
    assert (job["kind"], job["status"], job["progress"], job["stage"], job["error"]) == (
        "document_processing",
        "queued",
        0,
        None,
        None,
    )

    # The original is in S3 unchanged, under a key made only of IDs.
    key = f"cases/{DANIEL}/documents/{doc['id']}/original"
    assert s3_keys() == [f"{S3_PREFIX}{key}"]
    stored = s3_object(f"{S3_PREFIX}{key}")
    assert stored["body"] == data and stored["content_type"] == "application/pdf"
    assert "pay_stub" not in key and ".pdf" not in key

    [row] = await rows(
        session,
        "SELECT case_id, file_name, s3_key, sha256, mime, size_bytes, status, declared_type "
        "FROM documents WHERE id = :d",
        d=doc["id"],
    )
    assert tuple(row) == (
        DANIEL,
        "pay_stub_2026-09-27.pdf",
        key,  # stored relative to S3_PREFIX
        hashlib.sha256(data).hexdigest(),
        "application/pdf",
        len(data),
        "uploaded",
        None,
    )
    [job_row] = await rows(
        session, "SELECT kind, case_id, document_id, status FROM jobs WHERE id = :j", j=job["id"]
    )
    assert tuple(job_row) == ("document_processing", DANIEL, uuid.UUID(doc["id"]), "queued")
    assert fake_queue.calls == [("process_documents", (job["id"], [doc["id"]]), job["id"])]


async def test_every_upload_writes_an_audit_event(
    docs_client: httpx.AsyncClient, session: AsyncSession, rendered: Rendered
) -> None:
    data = rendered.read(STUB)
    response = await upload(docs_client, DANIEL, [("stub.pdf", data)], declared_type="pay_stub")
    [doc] = response.json()["documents"]

    [event] = await rows(
        session,
        "SELECT actor_id, role, action, entity_type, entity_id, case_id, after "
        "FROM audit_events WHERE action = 'document.uploaded'",
    )
    assert event.actor_id == user_id("underwriter") and event.role == "underwriter"
    assert (event.entity_type, event.entity_id, event.case_id) == (
        "document",
        uuid.UUID(doc["id"]),
        DANIEL,
    )
    assert event.after == {
        "file_name": "stub.pdf",
        "sha256": hashlib.sha256(data).hexdigest(),
        "size_bytes": len(data),
        "mime": "application/pdf",
        "declared_type": "pay_stub",
    }


async def test_several_files_make_several_documents_and_one_job(
    docs_client: httpx.AsyncClient,
    session: AsyncSession,
    rendered: Rendered,
    fake_queue: FakeQueue,
) -> None:
    names = [("a_stub.pdf", STUB), ("b_august.pdf", AUGUST), ("c_september.pdf", SEPTEMBER)]

    response = await upload(docs_client, DANIEL, [(n, rendered.read(p)) for n, p in names])

    assert response.status_code == 202
    body = response.json()
    assert [d["file_name"] for d in body["documents"]] == [n for n, _ in names]  # upload order
    ids = [d["id"] for d in body["documents"]]
    assert len(set(ids)) == 3 and len(s3_keys()) == 3
    assert fake_queue.calls == [("process_documents", (body["job"]["id"], ids), body["job"]["id"])]
    assert await counts(session) == {"documents": 3, "jobs": 1, "audit_events": 3}
    [job_row] = await rows(session, "SELECT document_id FROM jobs")
    assert job_row.document_id is None  # a batch job belongs to no single document
    events = await rows(
        session, "SELECT entity_id FROM audit_events WHERE action = 'document.uploaded' ORDER BY id"
    )
    assert [str(e.entity_id) for e in events] == ids


async def test_the_declared_type_is_kept_and_auto_means_none(
    docs_client: httpx.AsyncClient, rendered: Rendered
) -> None:
    data = rendered.read(STUB)
    typed = await upload(docs_client, DANIEL, [("a.pdf", data)], declared_type="pay_stub")
    auto = await upload(
        docs_client, DANIEL, [("b.pdf", rendered.read(AUGUST))], declared_type="auto"
    )
    assert typed.json()["documents"][0]["declared_type"] == "pay_stub"
    assert auto.json()["documents"][0]["declared_type"] is None


async def test_an_unknown_declared_type_is_a_validation_error_and_stores_nothing(
    docs_client: httpx.AsyncClient, session: AsyncSession, rendered: Rendered
) -> None:
    response = await upload(
        docs_client, DANIEL, [("a.pdf", rendered.read(STUB))], declared_type="payslip"
    )
    assert response.status_code == 422 and response.json()["code"] == "validation_failed"
    assert s3_keys() == [] and (await counts(session))["documents"] == 0


async def test_the_original_is_stored_as_the_exact_bytes_whatever_the_name(
    docs_client: httpx.AsyncClient, session: AsyncSession, rendered: Rendered
) -> None:
    data = rendered.read(STUB)
    response = await upload(docs_client, DANIEL, [("C:\\Users\\daniel\\..\\stub.csv", data)])
    [doc] = response.json()["documents"]
    assert doc["file_name"] == "stub.csv"  # a base name only; the type comes from the bytes
    [key] = s3_keys()
    assert s3_object(key)["body"] == data
    assert "stub" not in key and "daniel" not in key
    assert (await rows(session, "SELECT mime FROM documents"))[0].mime == "application/pdf"


async def test_pngs_and_jpegs_are_accepted(
    docs_client: httpx.AsyncClient, rendered: Rendered
) -> None:
    jpeg = rendered.read("broken/scan_mortgage_statement.jpg")
    response = await upload(docs_client, ANGELA, [("scan.jpg", jpeg)], role=Role.LM_SPECIALIST)
    assert response.status_code == 202
    [key] = s3_keys()
    assert s3_object(key)["content_type"] == "image/jpeg" and s3_object(key)["body"] == jpeg


# --- files that are refused -----------------------------------------------------------------


async def test_a_csv_is_refused_as_unsupported_media(
    docs_client: httpx.AsyncClient, session: AsyncSession, rendered: Rendered
) -> None:
    response = await upload(docs_client, DANIEL, [("export.csv", rendered.read(CSV))])
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


@pytest.mark.parametrize(
    "name",
    ["statement.pdf", "statement.png", "statement"],
    ids=["pdf-extension", "png-extension", "no-extension"],
)
async def test_the_extension_cannot_make_a_csv_acceptable(
    docs_client: httpx.AsyncClient, rendered: Rendered, name: str
) -> None:
    response = await upload(docs_client, DANIEL, [(name, rendered.read(CSV))])
    assert response.status_code == 415


async def test_an_empty_file_is_refused(docs_client: httpx.AsyncClient) -> None:
    response = await upload(docs_client, DANIEL, [("empty.pdf", b"")])
    assert response.status_code == 415 and response.json()["code"] == "unsupported_media"


async def test_one_bad_file_refuses_the_whole_upload(
    docs_client: httpx.AsyncClient,
    session: AsyncSession,
    rendered: Rendered,
    fake_queue: FakeQueue,
) -> None:
    response = await upload(
        docs_client,
        DANIEL,
        [("good.pdf", rendered.read(STUB)), ("export.csv", rendered.read(CSV))],
    )
    assert response.status_code == 415 and response.json()["details"] == {"file_name": "export.csv"}
    assert s3_keys() == [] and fake_queue.calls == []
    assert await counts(session) == {"documents": 0, "jobs": 0, "audit_events": 0}


async def test_a_file_over_the_limit_is_too_large(
    docs_client: httpx.AsyncClient, session: AsyncSession
) -> None:
    app.dependency_overrides[get_ingestion_config] = lambda: get_ingestion_config().model_copy(
        update={"max_file_mb": 1}
    )
    pdf = b"%PDF-1.7\n"
    at_limit = pdf + b"\x00" * (MIB - len(pdf))

    too_big = await upload(docs_client, DANIEL, [("big.pdf", at_limit + b"\x00")])
    assert too_big.status_code == 413
    assert too_big.json() == {
        "code": "too_large",
        "message": "We couldn't use big.pdf: it is larger than 1 MB.",
        "details": {"file_name": "big.pdf"},
    }
    assert s3_keys() == []

    exactly = await upload(docs_client, DANIEL, [("exact.pdf", at_limit)])
    assert exactly.status_code == 202  # a file of exactly the limit is fine


async def test_the_limit_comes_from_the_shipped_config() -> None:
    assert get_ingestion_config().max_file_bytes == 25 * MIB


async def test_an_upload_with_no_files_is_a_validation_error(
    docs_client: httpx.AsyncClient,
) -> None:
    response = await docs_client.post(
        f"/api/v1/cases/{DANIEL}/documents",
        data={"declared_type": "auto"},
        headers=auth_headers(Role.UNDERWRITER),
    )
    assert response.status_code == 422 and response.json()["code"] == "validation_failed"


# --- who may upload where -------------------------------------------------------------------


async def test_an_upload_needs_a_token(docs_client: httpx.AsyncClient, rendered: Rendered) -> None:
    response = await docs_client.post(
        f"/api/v1/cases/{DANIEL}/documents",
        files=[("files", ("a.pdf", rendered.read(STUB), "application/pdf"))],
    )
    assert response.status_code == 401 and response.json()["code"] == "unauthorized"
    assert (await docs_client.get(f"/api/v1/cases/{DANIEL}/documents")).status_code == 401


@pytest.mark.parametrize("target", [str(uuid.uuid4()), "not-a-uuid"])
async def test_an_unknown_case_is_404(
    docs_client: httpx.AsyncClient, session: AsyncSession, rendered: Rendered, target: str
) -> None:
    response = await upload(docs_client, target, [("a.pdf", rendered.read(STUB))])
    assert response.status_code == 404 and response.json()["code"] == "not_found"
    assert s3_keys() == [] and (await counts(session))["documents"] == 0


async def test_a_case_in_another_pillar_looks_like_a_case_that_does_not_exist(
    docs_client: httpx.AsyncClient, session: AsyncSession, rendered: Rendered
) -> None:
    hidden = await upload(
        docs_client, DANIEL, [("a.pdf", rendered.read(STUB))], role=Role.LM_SPECIALIST
    )
    missing = await upload(
        docs_client, uuid.uuid4(), [("a.pdf", rendered.read(STUB))], role=Role.LM_SPECIALIST
    )
    assert hidden.status_code == missing.status_code == 404
    assert hidden.json() == missing.json()
    assert s3_keys() == [] and (await counts(session))["documents"] == 0
    listed = await docs_client.get(
        f"/api/v1/cases/{DANIEL}/documents", headers=auth_headers(Role.LM_SPECIALIST)
    )
    assert listed.status_code == 404


@pytest.mark.parametrize(
    ("role", "case"),
    [
        (Role.UNDERWRITER, DANIEL),
        (Role.LM_SPECIALIST, ANGELA),
        (Role.ADMIN, DANIEL),
        (Role.ADMIN, ANGELA),
    ],
)
async def test_each_role_can_upload_to_the_cases_it_can_see(
    docs_client: httpx.AsyncClient, rendered: Rendered, role: Role, case: uuid.UUID
) -> None:
    response = await upload(docs_client, case, [("a.pdf", rendered.read(STUB))], role=role)
    assert response.status_code == 202


# --- when storage or the queue fails --------------------------------------------------------


async def test_a_storage_failure_leaves_nothing_behind(
    docs_client: httpx.AsyncClient,
    session: AsyncSession,
    s3_storage: Storage,
    rendered: Rendered,
    fake_queue: FakeQueue,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    real_put, calls = s3_storage.put, []

    def flaky_put(key: str, data: bytes, content_type: str | None = None) -> str:
        calls.append(key)
        if len(calls) == 2:
            raise StorageError("put failed: InternalError")
        return real_put(key, data, content_type)

    monkeypatch.setattr(s3_storage, "put", flaky_put)

    response = await upload(
        docs_client,
        DANIEL,
        [("a.pdf", rendered.read(STUB)), ("b.pdf", rendered.read(AUGUST))],
    )

    assert response.status_code == 503
    assert response.json() == {
        "code": "storage_unavailable",
        "message": "The file could not be stored. Please try again.",
    }
    assert s3_keys() == []  # the first file was removed again
    assert fake_queue.calls == []
    assert await counts(session) == {"documents": 0, "jobs": 0, "audit_events": 0}


async def test_a_connection_error_to_s3_is_a_503_not_a_crash(
    docs_client: httpx.AsyncClient,
    session: AsyncSession,
    s3_storage: Storage,
    rendered: Rendered,
    fake_queue: FakeQueue,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # botocore raises EndpointConnectionError (not ClientError) when S3 cannot be reached. It
    # used to escape as a 500; it is the same "storage_unavailable" as any other storage failure.
    client = s3_storage._get_client()
    real_put_object, calls = client.put_object, []

    def unreachable_on_second(**kwargs: Any) -> Any:
        calls.append(kwargs["Key"])
        if len(calls) == 2:
            raise EndpointConnectionError(endpoint_url="https://s3.example.invalid/secret-key")
        return real_put_object(**kwargs)

    monkeypatch.setattr(client, "put_object", unreachable_on_second)

    response = await upload(
        docs_client,
        DANIEL,
        [("a.pdf", rendered.read(STUB)), ("b.pdf", rendered.read(AUGUST))],
    )

    assert response.status_code == 503
    assert response.json()["code"] == "storage_unavailable"
    assert "secret-key" not in response.text  # the failing URL is never echoed
    assert s3_keys() == []  # the first file was removed again
    assert fake_queue.calls == []
    assert await counts(session) == {"documents": 0, "jobs": 0, "audit_events": 0}


async def test_a_database_failure_removes_the_stored_files(
    docs_client: httpx.AsyncClient,
    session: AsyncSession,
    rendered: Rendered,
    fake_queue: FakeQueue,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def broken_commit() -> None:
        raise sa.exc.OperationalError("COMMIT", {}, Exception("connection lost"))

    monkeypatch.setattr(session, "commit", broken_commit)

    with pytest.raises(sa.exc.OperationalError):
        await upload(docs_client, DANIEL, [("a.pdf", rendered.read(STUB))])

    assert s3_keys() == [] and fake_queue.calls == []


async def test_a_queue_failure_keeps_the_upload_but_fails_the_job(
    docs_client: httpx.AsyncClient,
    session: AsyncSession,
    rendered: Rendered,
    fake_queue: FakeQueue,
) -> None:
    fake_queue.fail = True

    response = await upload(docs_client, DANIEL, [("a.pdf", rendered.read(STUB))])

    assert response.status_code == 503 and response.json()["code"] == "queue_unavailable"
    assert len(s3_keys()) == 1  # saved: a retry will show it as a duplicate
    [job] = await rows(session, "SELECT status, error FROM jobs")
    assert job.status == "failed" and "could not be queued" in job.error
    assert (await counts(session))["documents"] == 1


# --- duplicates are accepted and flagged ----------------------------------------------------


async def test_the_same_file_twice_is_accepted_and_the_second_is_flagged(
    docs_client: httpx.AsyncClient, session: AsyncSession, rendered: Rendered
) -> None:
    data = rendered.read(STUB)

    first = await upload(docs_client, DANIEL, [("pay_stub.pdf", data)])
    second = await upload(docs_client, DANIEL, [("duplicate_pay_stub.pdf", data)])

    assert first.status_code == second.status_code == 202  # never refused (FSD DI-W206)
    assert first.json()["documents"][0]["flags"] == []
    assert second.json()["documents"][0]["flags"] == [DUPLICATE_FLAG]
    assert len(s3_keys()) == 2 and (await counts(session))["documents"] == 2
    listed = await docs_client.get(
        f"/api/v1/cases/{DANIEL}/documents", headers=auth_headers(Role.UNDERWRITER)
    )
    assert [d["flags"] for d in listed.json()["items"]] == [[], [DUPLICATE_FLAG]]


async def test_a_duplicate_inside_one_upload_flags_the_later_file(
    docs_client: httpx.AsyncClient, rendered: Rendered
) -> None:
    data = rendered.read(STUB)
    response = await upload(
        docs_client,
        DANIEL,
        [("one.pdf", data), ("two.pdf", rendered.read(AUGUST)), ("three.pdf", data)],
    )
    assert [d["flags"] for d in response.json()["documents"]] == [[], [], [DUPLICATE_FLAG]]


async def test_the_same_file_in_another_case_is_not_a_duplicate(
    docs_client: httpx.AsyncClient, rendered: Rendered
) -> None:
    data = rendered.read(STUB)
    await upload(docs_client, DANIEL, [("a.pdf", data)])
    other = await upload(docs_client, ANGELA, [("a.pdf", data)], role=Role.LM_SPECIALIST)
    assert other.json()["documents"][0]["flags"] == []


# --- listing --------------------------------------------------------------------------------


async def test_a_new_case_has_no_documents(docs_client: httpx.AsyncClient) -> None:
    response = await docs_client.get(
        f"/api/v1/cases/{DANIEL}/documents", headers=auth_headers(Role.UNDERWRITER)
    )
    assert response.status_code == 200 and response.json() == {"items": []}


async def test_the_list_is_in_upload_order_and_uses_the_contracts_names(
    docs_client: httpx.AsyncClient, session: AsyncSession, rendered: Rendered
) -> None:
    await upload(
        docs_client, DANIEL, [("b.pdf", rendered.read(AUGUST)), ("a.pdf", rendered.read(STUB))]
    )
    await upload(docs_client, DANIEL, [("c.pdf", rendered.read(SEPTEMBER))])
    await session.execute(
        sa.text(
            "UPDATE documents SET doc_type = 'pay_stub', doc_type_certainty = 'high', "
            "borrower = 'Daniel Reyes', page_count = 2, summary = 'A pay stub.' "
            "WHERE file_name = 'a.pdf'"
        )
    )

    response = await docs_client.get(
        f"/api/v1/cases/{DANIEL}/documents", headers=auth_headers(Role.UNDERWRITER)
    )

    items = response.json()["items"]
    assert [i["file_name"] for i in items] == ["b.pdf", "a.pdf", "c.pdf"]
    assert all(set(i) == set(DocumentSummaryOut.model_fields) for i in items)
    stub = items[1]
    assert (stub["doc_type"], stub["type_certainty"], stub["owner"], stub["page_count"]) == (
        "pay_stub",
        "high",
        "Daniel Reyes",
        2,
    )
    assert stub["summary"] == "A pay stub." and stub["uploaded_at"].endswith("Z")
    for hidden in ("s3_key", "sha256", "mime", "size_bytes", "borrower", "created_at"):
        assert hidden not in stub


async def test_the_list_only_shows_that_cases_documents(
    docs_client: httpx.AsyncClient, rendered: Rendered
) -> None:
    await upload(docs_client, DANIEL, [("daniel.pdf", rendered.read(STUB))])
    await upload(
        docs_client, ANGELA, [("angela.pdf", rendered.read(AUGUST))], role=Role.LM_SPECIALIST
    )
    response = await docs_client.get(
        f"/api/v1/cases/{ANGELA}/documents", headers=auth_headers(Role.LM_SPECIALIST)
    )
    assert [i["file_name"] for i in response.json()["items"]] == ["angela.pdf"]


async def test_the_case_overview_counts_the_uploaded_documents(
    docs_client: httpx.AsyncClient, rendered: Rendered
) -> None:
    await upload(
        docs_client, DANIEL, [("a.pdf", rendered.read(STUB)), ("b.pdf", rendered.read(AUGUST))]
    )
    case = await docs_client.get(f"/api/v1/cases/{DANIEL}", headers=auth_headers(Role.UNDERWRITER))
    assert case.json()["document_count"] == 2


async def test_needs_review_keeps_only_documents_awaiting_a_reviewer(
    docs_client: httpx.AsyncClient, session: AsyncSession, rendered: Rendered
) -> None:
    await upload(
        docs_client, DANIEL, [("a.pdf", rendered.read(STUB)), ("b.pdf", rendered.read(AUGUST))]
    )
    await session.execute(
        sa.text("UPDATE documents SET status = 'needs_review' WHERE file_name = 'b.pdf'")
    )
    headers = auth_headers(Role.UNDERWRITER)
    url = f"/api/v1/cases/{DANIEL}/documents"

    only = await docs_client.get(url, params={"needs_review": "true"}, headers=headers)
    everything = await docs_client.get(url, params={"needs_review": "false"}, headers=headers)
    plain = await docs_client.get(url, headers=headers)

    assert [i["file_name"] for i in only.json()["items"]] == ["b.pdf"]
    assert [i["file_name"] for i in everything.json()["items"]] == ["a.pdf", "b.pdf"]
    assert plain.json() == everything.json()
    bad = await docs_client.get(url, params={"needs_review": "maybe"}, headers=headers)
    assert bad.status_code == 422

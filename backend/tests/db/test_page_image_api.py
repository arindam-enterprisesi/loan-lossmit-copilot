"""GET /cases/{case_id}/documents/{document_id}/pages/{page}: a 5-minute link to a page image.

The review screen shows the page image next to the extracted fields and draws each field's box on
it (boxes are fractions of the image, so the viewer needs the image's width and height). The image
itself is private in S3; this endpoint hands out a short-lived presigned link, only to a user who
may see the case.
"""

from __future__ import annotations

import io
import uuid
from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
import requests
from PIL import Image
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.enums import Role
from app.db.models import Document, Page
from app.db.seed import case_id, seed
from app.services.storage_keys import page_image_key
from app.storage import PRESIGN_SECONDS, Storage, StorageError
from tests.db.conftest import auth_headers

DANIEL = case_id("Daniel Reyes — purchase")  # underwriting
ANGELA = case_id("Angela Whitfield — hardship")  # loss_mitigation
PAGE_SIZE = (1654, 2339)  # A4 at 200 dpi, as the pages table stores it


@pytest.fixture(autouse=True)
async def seeded(session: AsyncSession) -> None:
    await seed(session, "demo-pass")


def png(colour: str) -> bytes:
    out = io.BytesIO()
    Image.new("RGB", (8, 4), colour).save(out, format="PNG")
    return out.getvalue()


async def make_document(
    session: AsyncSession, storage: Storage, case: uuid.UUID, colours: list[str]
) -> uuid.UUID:
    """A document with one stored image per colour, as ingestion leaves it."""
    document = Document(
        case_id=case,
        file_name="stub.pdf",
        s3_key=f"k/{uuid.uuid4().hex}",
        sha256=uuid.uuid4().hex * 2,
        mime="application/pdf",
        size_bytes=1,
        page_count=len(colours),
    )
    session.add(document)
    await session.flush()
    for number, colour in enumerate(colours, start=1):
        key = page_image_key(case, document.id, number)
        storage.put(key, png(colour), "image/png")
        session.add(
            Page(
                document_id=document.id,
                page_no=number,
                image_s3_key=key,
                width=PAGE_SIZE[0],
                height=PAGE_SIZE[1],
            )
        )
    await session.flush()
    return document.id


def url_of(case: uuid.UUID | str, document: uuid.UUID | str, page: int | str) -> str:
    return f"/api/v1/cases/{case}/documents/{document}/pages/{page}"


async def get(
    client: httpx.AsyncClient,
    case: uuid.UUID | str,
    document: uuid.UUID | str,
    page: int | str,
    role: Role = Role.UNDERWRITER,
) -> httpx.Response:
    return await client.get(url_of(case, document, page), headers=auth_headers(role))


async def test_a_page_comes_back_as_a_link_that_downloads_the_image(
    docs_client: httpx.AsyncClient, session: AsyncSession, s3_storage: Storage
) -> None:
    document = await make_document(session, s3_storage, DANIEL, ["red", "blue"])
    before = datetime.now(UTC)

    response = await get(docs_client, DANIEL, document, 1)

    after = datetime.now(UTC)
    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"page", "url", "expires_at", "width", "height"}
    assert (body["page"], body["width"], body["height"]) == (1, PAGE_SIZE[0], PAGE_SIZE[1])
    # It is the stored image, fetched with nothing but the link.
    assert requests.get(body["url"], timeout=10).content == png("red")
    # Valid for five minutes, and the response says when it stops working.
    assert parse_qs(urlparse(body["url"]).query)["X-Amz-Expires"] == [str(PRESIGN_SECONDS)]
    expires = datetime.fromisoformat(body["expires_at"])
    assert before + timedelta(seconds=PRESIGN_SECONDS) <= expires
    assert expires <= after + timedelta(seconds=PRESIGN_SECONDS)


async def test_each_page_has_its_own_image(
    docs_client: httpx.AsyncClient, session: AsyncSession, s3_storage: Storage
) -> None:
    document = await make_document(session, s3_storage, DANIEL, ["red", "blue"])

    second = (await get(docs_client, DANIEL, document, 2)).json()

    assert second["page"] == 2
    assert requests.get(second["url"], timeout=10).content == png("blue")


@pytest.mark.parametrize("page", [0, 3, -1, "abc", "1.5", "99999999999999999999"])
async def test_a_page_that_is_not_there_is_a_404(
    docs_client: httpx.AsyncClient, session: AsyncSession, s3_storage: Storage, page: int | str
) -> None:
    document = await make_document(session, s3_storage, DANIEL, ["red", "blue"])

    response = await get(docs_client, DANIEL, document, page)

    assert response.status_code == 404
    assert response.json()["code"] == "not_found"


async def test_an_unknown_or_malformed_document_is_a_404(
    docs_client: httpx.AsyncClient,
) -> None:
    for document in (uuid.uuid4(), "not-a-uuid"):
        response = await get(docs_client, DANIEL, document, 1)
        assert response.status_code == 404


async def test_a_document_of_another_case_is_a_404(
    docs_client: httpx.AsyncClient, session: AsyncSession, s3_storage: Storage
) -> None:
    other = await make_document(session, s3_storage, ANGELA, ["red"])

    # Angela's document, asked for through Daniel's case.
    assert (await get(docs_client, DANIEL, other, 1)).status_code == 404


async def test_a_case_the_role_cannot_see_is_a_404_with_no_hint(
    docs_client: httpx.AsyncClient, session: AsyncSession, s3_storage: Storage
) -> None:
    document = await make_document(session, s3_storage, ANGELA, ["red"])

    hidden = await get(docs_client, ANGELA, document, 1, Role.UNDERWRITER)
    visible = await get(docs_client, ANGELA, document, 1, Role.LM_SPECIALIST)

    assert hidden.status_code == 404 and hidden.json()["message"] == "Case not found"
    assert visible.status_code == 200
    assert "url" not in hidden.json()


async def test_an_unknown_case_is_a_404(docs_client: httpx.AsyncClient) -> None:
    assert (await get(docs_client, uuid.uuid4(), uuid.uuid4(), 1)).status_code == 404
    assert (await get(docs_client, "nope", uuid.uuid4(), 1)).status_code == 404


async def test_the_admin_may_look(
    docs_client: httpx.AsyncClient, session: AsyncSession, s3_storage: Storage
) -> None:
    document = await make_document(session, s3_storage, DANIEL, ["red"])
    assert (await get(docs_client, DANIEL, document, 1, Role.ADMIN)).status_code == 200


async def test_no_token_is_a_401(docs_client: httpx.AsyncClient) -> None:
    response = await docs_client.get(url_of(DANIEL, uuid.uuid4(), 1))
    assert response.status_code == 401


async def test_a_storage_failure_is_a_503(
    docs_client: httpx.AsyncClient,
    session: AsyncSession,
    s3_storage: Storage,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    document = await make_document(session, s3_storage, DANIEL, ["red"])

    def broken(key: str, expires: int = PRESIGN_SECONDS) -> str:
        raise StorageError("presign failed: EndpointConnectionError")

    monkeypatch.setattr(s3_storage, "presigned_get", broken)

    response = await get(docs_client, DANIEL, document, 1)

    assert response.status_code == 503
    assert response.json()["code"] == "storage_unavailable"
    assert "EndpointConnectionError" not in response.text  # the cause stays in the log

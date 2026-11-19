"""Documents: validate and store an upload, queue its ingestion, and list a case's documents.

An upload is checked in full before anything is stored: size, then type (from the file's own
bytes, never the client's content type or extension), then a SHA-256. The original goes to S3
unchanged under a key made only of IDs. A file that is already in the case is accepted, and
shown with a warning flag (FSD DI-W206, "Keep it anyway?"); it is never refused.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import re
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.db.enums import DocumentStatus, DocumentType, JobStatus
from app.db.models import Document, Job
from app.services import audit
from app.services.queue import INGEST_FUNCTION, JobQueue
from app.services.security import CurrentUser
from app.services.storage_keys import original_key
from app.storage import Storage, StorageError

logger = logging.getLogger(__name__)

INGEST_JOB_KIND = "document_ingest"
MAX_FILE_NAME_LENGTH = 255

# The first bytes of each accepted type (contracts/openapi.yaml: PDF, PNG or JPEG).
SIGNATURES: tuple[tuple[bytes, str], ...] = (
    (b"%PDF-", "application/pdf"),
    (b"\x89PNG\r\n\x1a\n", "image/png"),
    (b"\xff\xd8\xff", "image/jpeg"),
)

_CONTROL_CHARACTERS = re.compile(r"[\x00-\x1f\x7f]")


class UploadRejectedError(Exception):
    """A file in the upload cannot be accepted."""

    def __init__(
        self, kind: Literal["too_large", "unsupported_media"], file_name: str, message: str
    ):
        super().__init__(message)
        self.kind = kind
        self.file_name = file_name
        self.message = message


class UploadFailedError(Exception):
    """The upload was valid but could not be completed (storage or queue unavailable)."""

    def __init__(self, kind: Literal["storage_unavailable", "queue_unavailable"], message: str):
        super().__init__(message)
        self.kind = kind
        self.message = message


@dataclass(frozen=True)
class ValidatedFile:
    file_name: str
    data: bytes
    mime: str
    sha256: str

    @property
    def size_bytes(self) -> int:
        return len(self.data)


@dataclass(frozen=True)
class DocumentView:
    document: Document
    duplicate: bool  # an earlier document in the same case has the same SHA-256


@dataclass(frozen=True)
class UploadResult:
    documents: list[DocumentView]
    job: Job


def sniff_mime(data: bytes) -> str | None:
    for signature, mime in SIGNATURES:
        if data.startswith(signature):
            return mime
    return None


def safe_file_name(raw: str | None) -> str:
    """The base name only (no folders), without control characters, at most 255 characters."""
    name = _CONTROL_CHARACTERS.sub("", (raw or "").replace("\\", "/").rsplit("/", 1)[-1]).strip()
    return name[:MAX_FILE_NAME_LENGTH] or "upload"


def validate_file(raw_name: str | None, data: bytes, max_bytes: int) -> ValidatedFile:
    """Check size and type. ``data`` may be one byte longer than the limit to prove it is over."""
    name = safe_file_name(raw_name)
    if len(data) > max_bytes:
        raise UploadRejectedError(
            "too_large",
            name,
            f"We couldn't use {name}: it is larger than {max_bytes // (1024 * 1024)} MB.",
        )
    mime = sniff_mime(data)
    if mime is None:
        raise UploadRejectedError(
            "unsupported_media",
            name,
            f"We couldn't use {name}: only PDF, PNG and JPEG files are accepted.",
        )
    return ValidatedFile(name, data, mime, hashlib.sha256(data).hexdigest())


async def _delete_quietly(storage: Storage, keys: list[str]) -> None:
    for key in keys:
        try:
            await asyncio.to_thread(storage.delete, key)
        except StorageError:
            logger.warning("could not remove stored file %s after a failed upload", key)


async def upload_documents(
    session: AsyncSession,
    storage: Storage,
    queue: JobQueue,
    user: CurrentUser,
    case_id: uuid.UUID,
    files: list[ValidatedFile],
    declared_type: DocumentType | None,
) -> UploadResult:
    """Store the files, record them, and queue one ingestion job for all of them.

    Unlike the other services this commits, because the job must be queued only after the rows
    exist. If anything fails, files already stored are removed again.
    """
    stored: list[str] = []
    documents: list[Document] = []
    started = datetime.now(UTC)
    try:
        for index, file in enumerate(files):
            document_id = uuid.uuid4()
            key = original_key(case_id, document_id)
            try:
                await asyncio.to_thread(storage.put, key, file.data, file.mime)
            except StorageError as exc:
                logger.warning("storing an upload failed: %s", exc)
                raise UploadFailedError(
                    "storage_unavailable", "The file could not be stored. Please try again."
                ) from exc
            stored.append(key)
            documents.append(
                Document(
                    id=document_id,
                    case_id=case_id,
                    file_name=file.file_name,
                    s3_key=key,
                    sha256=file.sha256,
                    mime=file.mime,
                    size_bytes=file.size_bytes,
                    declared_type=declared_type.value if declared_type else None,
                    status=DocumentStatus.UPLOADED,
                    # Distinct and increasing, so upload order survives and "earlier" is exact.
                    created_at=started + timedelta(microseconds=index),
                )
            )

        job = Job(
            kind=INGEST_JOB_KIND,
            case_id=case_id,
            document_id=documents[0].id if len(documents) == 1 else None,
            status=JobStatus.QUEUED,
        )
        session.add_all([*documents, job])
        await session.flush()
        for document, file in zip(documents, files, strict=True):
            await audit.record(
                session,
                actor_id=uuid.UUID(user.id),
                role=user.role.value,
                action="document.uploaded",
                entity_type="document",
                entity_id=document.id,
                case_id=case_id,
                after={
                    "file_name": file.file_name,
                    "sha256": file.sha256,
                    "size_bytes": file.size_bytes,
                    "mime": file.mime,
                    "declared_type": document.declared_type,
                },
            )
        await session.commit()
    except BaseException:
        await session.rollback()
        await _delete_quietly(storage, stored)
        raise

    try:
        await queue.enqueue(
            INGEST_FUNCTION, str(job.id), [str(d.id) for d in documents], job_id=str(job.id)
        )
    except Exception as exc:
        logger.warning("queueing job %s failed: %s", job.id, type(exc).__name__)
        job.status = JobStatus.FAILED
        job.error = "The upload was saved but could not be queued for reading."
        await session.commit()
        raise UploadFailedError(
            "queue_unavailable", "The upload was saved but could not be queued. Please try again."
        ) from exc

    await session.refresh(job)
    return UploadResult(await _views(session, case_id, [d.id for d in documents]), job)


def _is_duplicate() -> sa.ColumnElement[bool]:
    earlier = aliased(Document)
    return sa.exists().where(
        earlier.case_id == Document.case_id,
        earlier.sha256 == Document.sha256,
        sa.tuple_(earlier.created_at, earlier.id) < sa.tuple_(Document.created_at, Document.id),
    )


async def _views(
    session: AsyncSession,
    case_id: uuid.UUID,
    only: list[uuid.UUID] | None = None,
    needs_review: bool | None = None,
) -> list[DocumentView]:
    query = sa.select(Document, _is_duplicate().label("duplicate")).where(
        Document.case_id == case_id
    )
    if only is not None:
        query = query.where(Document.id.in_(only))
    if needs_review:
        query = query.where(Document.status == DocumentStatus.NEEDS_REVIEW)
    rows = await session.execute(query.order_by(Document.created_at, Document.id))
    return [DocumentView(document, duplicate) for document, duplicate in rows.all()]


async def list_documents(
    session: AsyncSession, case_id: uuid.UUID, needs_review: bool | None = None
) -> list[DocumentView]:
    """A case's documents in upload order. ``needs_review`` keeps those awaiting a reviewer."""
    return await _views(session, case_id, needs_review=needs_review)

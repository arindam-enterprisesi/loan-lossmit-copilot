"""Documents: upload, list, extraction, field review and type (contracts/openapi.yaml).

Every endpoint needs a logged-in user and a case that user may see (otherwise 404, like the
cases router). Files are validated, stored and queued in ``app.services.documents``; reading
them (pages, lines, type, fields, checks) happens in the background, in
``app.services.pipeline``. Review and type changes are in ``app.services.review``.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import UTC, datetime, timedelta
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, File, Form, Path, UploadFile
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CaseIdPath, case_not_found, get_current_user, get_storage, require_roles
from app.api.errors import ApiError
from app.api.schemas.documents import (
    DocumentList,
    DocumentSummaryOut,
    PageImageOut,
    UploadResult,
    flag_from_row,
    summary_from_view,
)
from app.api.schemas.extraction import (
    ExtractionOut,
    FieldOut,
    FieldReviewIn,
    TypeChangeAccepted,
    TypeChangeIn,
    field_from_row,
)
from app.api.schemas.jobs import JobOut
from app.db.enums import DocumentType, Role
from app.db.models import Document
from app.db.session import get_session
from app.services import cases as case_service
from app.services import documents as document_service
from app.services import review as review_service
from app.services.document_config import get_document_fields
from app.services.extraction import active_run, extraction_view
from app.services.flags import load_line_meta, open_flags
from app.services.ingestion_config import IngestionConfig, get_ingestion_config
from app.services.queue import JobQueue, get_queue
from app.services.security import CurrentUser
from app.storage import PRESIGN_SECONDS, Storage, StorageError

logger = logging.getLogger(__name__)

# pages.page_no is a 32-bit integer, so a larger number cannot name a page.
MAX_PAGE_NUMBER = 2**31 - 1

router = APIRouter(
    prefix="/cases/{case_id}/documents",
    tags=["documents"],
    dependencies=[Depends(require_roles(Role.UNDERWRITER, Role.LM_SPECIALIST, Role.ADMIN))],
)

User = Annotated[CurrentUser, Depends(get_current_user)]
Session = Annotated[AsyncSession, Depends(get_session)]
Files = Annotated[Storage, Depends(get_storage)]
Queue = Annotated[JobQueue, Depends(get_queue)]
Config = Annotated[IngestionConfig, Depends(get_ingestion_config)]

_REJECTED_STATUS = {"too_large": 413, "unsupported_media": 415}


@router.post("", status_code=202, response_model=UploadResult, operation_id="uploadDocuments")
async def upload_documents(
    case_id: CaseIdPath,
    user: User,
    session: Session,
    storage: Files,
    queue: Queue,
    config: Config,
    files: Annotated[list[UploadFile], File()],
    declared_type: Annotated[Literal["auto"] | DocumentType, Form()] = "auto",
) -> UploadResult:
    if await case_service.get_case(session, user.role, case_id) is None:
        raise case_not_found()

    # Check every file before storing any. Reading one byte past the limit is enough to know a
    # file is too big, without holding the whole of an enormous one.
    limit = config.max_file_bytes
    validated: list[document_service.ValidatedFile] = []
    for upload in files:
        try:
            data = await upload.read(limit + 1)
            validated.append(document_service.validate_file(upload.filename, data, limit))
        except document_service.UploadRejectedError as exc:
            raise ApiError(
                _REJECTED_STATUS[exc.kind],
                exc.kind,
                exc.message,
                details={"file_name": exc.file_name},
            ) from None

    try:
        outcome = await document_service.upload_documents(
            session,
            storage,
            queue,
            user,
            case_id,
            validated,
            None if declared_type == "auto" else DocumentType(declared_type),
        )
    except document_service.UploadFailedError as exc:
        raise ApiError(503, exc.kind, exc.message) from None
    return UploadResult.from_outcome(outcome)


@router.get("", response_model=DocumentList, operation_id="listDocuments")
async def list_documents(
    case_id: CaseIdPath, user: User, session: Session, needs_review: bool | None = None
) -> DocumentList:
    if await case_service.get_case(session, user.role, case_id) is None:
        raise case_not_found()
    views = await document_service.list_documents(session, case_id, needs_review)
    return DocumentList.from_views(views)


# --- one document: extraction, field review, type --------------------------------------------


def _document_not_found() -> ApiError:
    return ApiError(404, "not_found", "Document not found")


async def _visible_document(
    session: AsyncSession, user: CurrentUser, case_id: uuid.UUID, document_id: str
) -> Document:
    """The document, if its case is visible to the caller. Otherwise 404, never a hint."""
    if await case_service.get_case(session, user.role, case_id) is None:
        raise case_not_found()
    try:
        wanted = uuid.UUID(document_id)
    except ValueError:
        raise _document_not_found() from None
    document = await document_service.get_document(session, case_id, wanted)
    if document is None:
        raise _document_not_found()
    return document


@router.get("/{document_id}/extraction", response_model=ExtractionOut, operation_id="getExtraction")
async def get_extraction(
    case_id: CaseIdPath, document_id: str, user: User, session: Session
) -> ExtractionOut:
    document = await _visible_document(session, user, case_id, document_id)
    run = await active_run(session, document.id)
    if run is None:  # the contract allows only 401 and 404 here
        raise ApiError(404, "not_found", "This document has not been read yet")
    view = await extraction_view(session, document, run, get_document_fields())
    return ExtractionOut(
        document_id=document.id,
        run_id=run.id,
        doc_type=DocumentType(run.doc_type),
        fields=[
            field_from_row(row, document.id, row_flags, view.meta) for row, row_flags in view.fields
        ],
        flags=[flag_from_row(f) for f in view.document_flags],
        summary=document.summary,
        prompt_id=run.prompt_id,
        provider=run.provider,
        model=run.model,
    )


@router.get("/{document_id}/pages/{page}", response_model=PageImageOut, operation_id="getPageImage")
async def get_page_image(
    case_id: CaseIdPath, document_id: str, page: str, user: User, session: Session, storage: Files
) -> PageImageOut:
    """A 5-minute link to the stored image of one page, and the image's width and height."""
    document = await _visible_document(session, user, case_id, document_id)
    try:
        page_no = int(page)
    except ValueError:
        raise ApiError(404, "not_found", "Page not found") from None
    row = (
        await document_service.get_page(session, document.id, page_no)
        if 1 <= page_no <= MAX_PAGE_NUMBER
        else None
    )
    if row is None:
        raise ApiError(404, "not_found", "Page not found")
    issued = datetime.now(UTC)
    try:
        url = await asyncio.to_thread(storage.presigned_get, row.image_s3_key)
    except StorageError as exc:
        logger.warning("page link failed document=%s page=%d: %s", document.id, page_no, exc)
        raise ApiError(
            503, "storage_unavailable", "The page image is unavailable. Please try again."
        ) from None
    return PageImageOut(
        page=row.page_no,
        url=url,
        expires_at=issued + timedelta(seconds=PRESIGN_SECONDS),
        width=row.width,
        height=row.height,
    )


@router.patch(
    "/{document_id}/fields/{field_name}", response_model=FieldOut, operation_id="reviewField"
)
async def review_field(
    case_id: CaseIdPath,
    document_id: str,
    field_name: Annotated[str, Path(pattern=r"^[a-z][a-z0-9_]*$")],
    body: FieldReviewIn,
    user: User,
    session: Session,
) -> FieldOut:
    document = await _visible_document(session, user, case_id, document_id)
    try:
        row = await review_service.review_field(
            session,
            user,
            document,
            field_name,
            action=body.action,
            expected_version=body.expected_version,
            value=body.value,
            reason=body.reason,
        )
    except review_service.FieldNotFoundError:
        raise ApiError(404, "not_found", "Field not found") from None
    except review_service.EditConflictError:
        raise ApiError(
            409,
            "edit_conflict",
            "Someone else changed this value. Review the latest and try again.",
        ) from None
    except review_service.InvalidValueError as exc:
        raise ApiError(422, "validation_failed", str(exc), details={"field": field_name}) from None
    meta = await load_line_meta(session, document.id)
    flags_now = [f for f in await open_flags(session, document) if f.entity_id == row.id]
    out = field_from_row(row, document.id, flags_now, meta)
    await session.commit()
    return out


@router.put(
    "/{document_id}/type",
    response_model=None,
    operation_id="setDocumentType",
    responses={200: {"model": DocumentSummaryOut}, 202: {"model": TypeChangeAccepted}},
)
async def set_document_type(
    case_id: CaseIdPath,
    document_id: str,
    body: TypeChangeIn,
    user: User,
    session: Session,
    queue: Queue,
) -> JSONResponse:
    document = await _visible_document(session, user, case_id, document_id)
    try:
        change = await review_service.set_document_type(
            session, queue, user, document, body.doc_type.value, body.reason
        )
    except document_service.UploadFailedError as exc:
        raise ApiError(503, exc.kind, exc.message) from None
    summary = summary_from_view(await document_service.view_of(session, document))
    if change.job is None:
        return JSONResponse(summary.model_dump(mode="json"), status_code=200)
    accepted = TypeChangeAccepted(document=summary, job=JobOut.model_validate(change.job))
    return JSONResponse(accepted.model_dump(mode="json"), status_code=202)

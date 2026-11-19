"""Documents: uploadDocuments and listDocuments (contracts/openapi.yaml).

Every endpoint needs a logged-in user and a case that user may see (otherwise 404, like the
cases router). Files are validated, stored and queued in ``app.services.documents``; reading
them (pages, numbered lines) happens in the background, in ``app.services.ingestion``.
"""

from __future__ import annotations

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, File, Form, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CaseIdPath, case_not_found, get_current_user, get_storage, require_roles
from app.api.errors import ApiError
from app.api.schemas.documents import DocumentList, UploadResult
from app.db.enums import DocumentType, Role
from app.db.session import get_session
from app.services import cases as case_service
from app.services import documents as document_service
from app.services.ingestion_config import IngestionConfig, get_ingestion_config
from app.services.queue import JobQueue, get_queue
from app.services.security import CurrentUser
from app.storage import Storage

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

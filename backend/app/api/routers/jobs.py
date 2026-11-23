"""Jobs: getJob (contracts/openapi.yaml). The client polls this for long-running work."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, require_roles
from app.api.errors import ApiError
from app.api.schemas.jobs import JobOut
from app.db.enums import Role
from app.db.models import Job
from app.db.session import get_session
from app.services import cases as case_service
from app.services.security import CurrentUser

router = APIRouter(
    prefix="/jobs",
    tags=["jobs"],
    dependencies=[Depends(require_roles(Role.UNDERWRITER, Role.LM_SPECIALIST, Role.ADMIN))],
)

User = Annotated[CurrentUser, Depends(get_current_user)]
Session = Annotated[AsyncSession, Depends(get_session)]


def _not_found() -> ApiError:
    return ApiError(404, "not_found", "Job not found")


@router.get("/{job_id}", response_model=JobOut, operation_id="getJob")
async def get_job(job_id: str, user: User, session: Session) -> JobOut:
    """A job is visible to whoever can see its case; anything else looks like it does not exist."""
    try:
        wanted = uuid.UUID(job_id)
    except ValueError:
        raise _not_found() from None
    job = await session.get(Job, wanted)
    if job is None or job.case_id is None:
        raise _not_found()
    if await case_service.get_case(session, user.role, job.case_id) is None:
        raise _not_found()
    return JobOut.model_validate(job)

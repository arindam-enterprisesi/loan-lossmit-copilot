"""Cases: createCase, listCases, getCase, putCaseProfile (contracts/openapi.yaml).

Every endpoint needs a logged-in user. Which cases a role may see or create is
decided in ``app.services.cases``; a case the caller cannot see is a 404.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CaseIdPath, case_not_found, get_current_user, require_roles
from app.api.errors import forbidden
from app.api.schemas.cases import CaseCreate, CaseList, CaseOut, CaseProfile
from app.db.enums import Pillar, Role
from app.db.session import get_session
from app.services import cases as case_service
from app.services.security import CurrentUser

router = APIRouter(
    prefix="/cases",
    tags=["cases"],
    dependencies=[Depends(require_roles(Role.UNDERWRITER, Role.LM_SPECIALIST, Role.ADMIN))],
)

User = Annotated[CurrentUser, Depends(get_current_user)]
Session = Annotated[AsyncSession, Depends(get_session)]


@router.post("", status_code=201, response_model=CaseOut, operation_id="createCase")
async def create_case(body: CaseCreate, user: User, session: Session) -> CaseOut:
    if not case_service.can_access(user.role, body.pillar):
        raise forbidden("Your role cannot create cases in this pillar")
    view = await case_service.create_case(session, user, body.title, body.pillar)
    await session.commit()
    return CaseOut.from_view(view)


@router.get("", response_model=CaseList, operation_id="listCases")
async def list_cases(user: User, session: Session, pillar: Pillar | None = None) -> CaseList:
    views = await case_service.list_cases(session, user.role, pillar)
    return CaseList(items=[CaseOut.from_view(v) for v in views])


@router.get("/{case_id}", response_model=CaseOut, operation_id="getCase")
async def get_case(case_id: CaseIdPath, user: User, session: Session) -> CaseOut:
    view = await case_service.get_case(session, user.role, case_id)
    if view is None:
        raise case_not_found()
    return CaseOut.from_view(view)


@router.put("/{case_id}/profile", response_model=CaseProfile, operation_id="putCaseProfile")
async def put_case_profile(
    case_id: CaseIdPath, body: CaseProfile, user: User, session: Session
) -> CaseProfile:
    view = await case_service.set_profile(
        session,
        user,
        case_id,
        borrower_names=body.borrower_names,
        employment_type=body.employment_type,
        reference_date=body.reference_date,
    )
    if view is None:
        raise case_not_found()
    await session.commit()
    return body

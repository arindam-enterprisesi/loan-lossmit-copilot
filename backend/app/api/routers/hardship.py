"""Hardship assessment: the latest profile read from the borrower's letter (Feature Design 7.7).

Every endpoint needs a logged-in user and a case that user may see (otherwise 404, like the other
case routers), so a Pillar 1 case is invisible to the loss-mitigation specialist and the other way
round. This is the read side. Running a reading, confirming values and the budget come later.

The contract has no hardship endpoints yet (only a TODO that spells the path ``/hardship/profile``).
These follow the Feature Design's paths until it does.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CaseIdPath, case_not_found, get_current_user, require_roles
from app.api.errors import ApiError
from app.api.schemas.hardship import HardshipAssessmentOut, assessment_from_view
from app.db.enums import Role
from app.db.session import get_session
from app.prompts.schemas.hardship import HardshipConfig
from app.services import cases as case_service
from app.services import hardship_runs
from app.services.security import CurrentUser

router = APIRouter(
    prefix="/cases/{case_id}/hardship-assessment",
    tags=["hardship"],
    dependencies=[Depends(require_roles(Role.UNDERWRITER, Role.LM_SPECIALIST, Role.ADMIN))],
)

User = Annotated[CurrentUser, Depends(get_current_user)]
Session = Annotated[AsyncSession, Depends(get_session)]
Config = Annotated[HardshipConfig, Depends(hardship_runs.get_hardship_config)]


@router.get(
    "/latest", response_model=HardshipAssessmentOut, operation_id="getLatestHardshipAssessment"
)
async def get_latest_hardship_assessment(
    case_id: CaseIdPath, user: User, session: Session, config: Config
) -> HardshipAssessmentOut:
    """The newest profile: each item with its quote, its lines and whether the quote checks out."""
    if await case_service.get_case(session, user.role, case_id) is None:
        raise case_not_found()
    view = await hardship_runs.latest(session, case_id)
    if view is None:
        raise ApiError(404, "not_found", "No hardship assessment has been made for this case")
    return assessment_from_view(view, config)

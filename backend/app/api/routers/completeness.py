"""Completeness: run a checklist, read the latest result, override an item with a reason.

``POST`` and ``GET .../latest`` are in contracts/openapi.yaml. The override endpoint is not (the
contract's ``CompletenessItem`` already has ``override_reason``, but no endpoint sets it): it
follows the Feature Design ("the user can override an item with a written reason") until the
contract names one.

Every endpoint needs a logged-in user and a case that user may see (otherwise 404).
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CaseIdPath, case_not_found, get_current_user, require_roles
from app.api.errors import ApiError
from app.api.schemas.completeness import (
    CompletenessResultOut,
    CompletenessRunIn,
    ItemOverrideIn,
    result_from_view,
)
from app.db.enums import Role
from app.db.models import Case
from app.db.session import get_session
from app.services import cases as case_service
from app.services import completeness_runs
from app.services.analysis_config import AnalysisConfig, get_analysis_config
from app.services.security import CurrentUser

router = APIRouter(
    prefix="/cases/{case_id}/completeness",
    tags=["completeness"],
    dependencies=[Depends(require_roles(Role.UNDERWRITER, Role.LM_SPECIALIST, Role.ADMIN))],
)

User = Annotated[CurrentUser, Depends(get_current_user)]
Session = Annotated[AsyncSession, Depends(get_session)]
Config = Annotated[AnalysisConfig, Depends(get_analysis_config)]


async def _visible(session: AsyncSession, user: CurrentUser, case_id: uuid.UUID) -> Case:
    view = await case_service.get_case(session, user.role, case_id)
    if view is None:
        raise case_not_found()
    return view.case


@router.post("", response_model=CompletenessResultOut, operation_id="runCompleteness")
async def run_completeness(
    case_id: CaseIdPath, body: CompletenessRunIn, user: User, session: Session, cfg: Config
) -> CompletenessResultOut:
    """Check the case's documents against the checklist. Code decides every status."""
    case = await _visible(session, user, case_id)
    try:
        view = await completeness_runs.run_completeness(session, user, case, body.checklist_id, cfg)
    except completeness_runs.CompletenessError as exc:
        raise ApiError(exc.status, exc.code, exc.message) from None
    return result_from_view(view, cfg)


@router.get("/latest", response_model=CompletenessResultOut, operation_id="getLatestCompleteness")
async def get_latest_completeness(
    case_id: CaseIdPath, user: User, session: Session, cfg: Config
) -> CompletenessResultOut:
    await _visible(session, user, case_id)
    view = await completeness_runs.latest_view(session, case_id)
    if view is None:
        raise ApiError(404, "not_found", "No completeness check has been run for this case")
    return result_from_view(view, cfg)


@router.patch(
    "/latest/items/{item_id}",
    response_model=CompletenessResultOut,
    operation_id="overrideCompletenessItem",
)
async def override_completeness_item(
    case_id: CaseIdPath,
    item_id: str,
    body: ItemOverrideIn,
    user: User,
    session: Session,
    cfg: Config,
) -> CompletenessResultOut:
    """Override an item with a written reason (it counts as satisfied), or clear the override."""
    await _visible(session, user, case_id)
    try:
        view = await completeness_runs.set_override(
            session, user, case_id, item_id, action=body.action, reason=body.reason
        )
    except completeness_runs.CompletenessError as exc:
        raise ApiError(exc.status, exc.code, exc.message) from None
    return result_from_view(view, cfg)

"""Income analysis: run it, read the latest, include or exclude a component (Feature Design 2.7).

Every endpoint needs a logged-in user and a case that user may see (otherwise 404, like the other
case routers). Running is a background job (the client polls ``GET /jobs/{id}``); the analysis
itself is plain code in ``app.services.income``. Including or excluding a component recalculates at
once, with no AI call.

The contract has no income endpoints yet (only a TODO). These follow the Feature Design's paths
until it does.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CaseIdPath, case_not_found, get_current_user, require_roles
from app.api.errors import ApiError
from app.api.schemas.income import (
    ComponentReviewIn,
    IncomeAnalysisOut,
    IncomeRunAccepted,
    analysis_from_view,
)
from app.api.schemas.jobs import JobOut
from app.db.enums import Role
from app.db.session import get_session
from app.services import cases as case_service
from app.services import income_runs
from app.services.analysis_config import AnalysisConfig, get_analysis_config
from app.services.documents import UploadFailedError
from app.services.queue import JobQueue, get_queue
from app.services.security import CurrentUser

router = APIRouter(
    prefix="/cases/{case_id}/income-analysis",
    tags=["income"],
    dependencies=[Depends(require_roles(Role.UNDERWRITER, Role.LM_SPECIALIST, Role.ADMIN))],
)

User = Annotated[CurrentUser, Depends(get_current_user)]
Session = Annotated[AsyncSession, Depends(get_session)]
Queue = Annotated[JobQueue, Depends(get_queue)]
Config = Annotated[AnalysisConfig, Depends(get_analysis_config)]


async def _visible(session: AsyncSession, user: CurrentUser, case_id: uuid.UUID) -> None:
    if await case_service.get_case(session, user.role, case_id) is None:
        raise case_not_found()


@router.post(
    "", status_code=202, response_model=IncomeRunAccepted, operation_id="runIncomeAnalysis"
)
async def run_income_analysis(
    case_id: CaseIdPath, user: User, session: Session, queue: Queue
) -> IncomeRunAccepted:
    """Queue an analysis of the case's documents. Poll the job, then read ``/latest``."""
    await _visible(session, user, case_id)
    try:
        run, job = await income_runs.start_run(session, queue, user, case_id)
    except UploadFailedError as exc:
        raise ApiError(503, exc.kind, exc.message) from None
    return IncomeRunAccepted(job=JobOut.model_validate(job), analysis_id=run.id)


@router.get("/latest", response_model=IncomeAnalysisOut, operation_id="getLatestIncomeAnalysis")
async def get_latest_income_analysis(
    case_id: CaseIdPath, user: User, session: Session, cfg: Config
) -> IncomeAnalysisOut:
    """The newest analysis: components with current, year-to-date and monthly figures, flags."""
    await _visible(session, user, case_id)
    run = await income_runs.latest_run(session, case_id)
    if run is None:
        raise ApiError(404, "not_found", "No income analysis has been run for this case")
    return analysis_from_view(await income_runs.load_view(session, run), cfg)


@router.patch(
    "/latest/components/{component_id}",
    response_model=IncomeAnalysisOut,
    operation_id="reviewIncomeComponent",
)
async def review_income_component(
    case_id: CaseIdPath,
    component_id: str,
    body: ComponentReviewIn,
    user: User,
    session: Session,
    cfg: Config,
) -> IncomeAnalysisOut:
    """Include or exclude a component, with a reason. The candidate is recalculated at once."""
    await _visible(session, user, case_id)
    try:
        wanted = uuid.UUID(component_id)
    except ValueError:
        raise ApiError(404, "not_found", "Component not found") from None
    try:
        view = await income_runs.set_component_included(
            session, user, case_id, wanted, included=body.included, reason=body.reason
        )
    except income_runs.IncomeError as exc:
        raise ApiError(exc.status, exc.code, exc.message) from None
    return analysis_from_view(view, cfg)

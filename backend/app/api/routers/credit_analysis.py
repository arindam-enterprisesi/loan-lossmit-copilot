"""Credit report analysis: run it, read the latest (Feature Design 4.7).

Every endpoint needs a logged-in user and a case that user may see (otherwise 404, like the other
case routers). Running is a background job (the client polls ``GET /jobs/{id}``); the analysis
itself is plain code in ``app.services.credit`` over the report the pipeline already read: no model
is called here. The report is simulated and the response says so. It never decides anything.

The contract has no credit endpoints yet; ``docs/contract-proposal-d4.md`` has the YAML. The
annotation endpoint of the Feature Design (``PATCH .../items/{item}``) is not built.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CaseIdPath, case_not_found, get_current_user, require_roles
from app.api.errors import ApiError
from app.api.schemas.credit import CreditAnalysisOut, CreditRunAccepted, analysis_from_view
from app.api.schemas.jobs import JobOut
from app.db.enums import Role
from app.db.session import get_session
from app.services import cases as case_service
from app.services import credit_runs
from app.services.analysis_config import AnalysisConfig, get_analysis_config
from app.services.documents import UploadFailedError
from app.services.queue import JobQueue, get_queue
from app.services.security import CurrentUser

router = APIRouter(
    prefix="/cases/{case_id}/credit-analysis",
    tags=["credit"],
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
    "", status_code=202, response_model=CreditRunAccepted, operation_id="runCreditAnalysis"
)
async def run_credit_analysis(
    case_id: CaseIdPath, user: User, session: Session, queue: Queue
) -> CreditRunAccepted:
    """Queue an analysis of the case's credit report. Poll the job, then read ``/latest``."""
    await _visible(session, user, case_id)
    try:
        run, job = await credit_runs.start_run(session, queue, user, case_id)
    except UploadFailedError as exc:
        raise ApiError(503, exc.kind, exc.message) from None
    return CreditRunAccepted(job=JobOut.model_validate(job), analysis_id=run.id)


@router.get("/latest", response_model=CreditAnalysisOut, operation_id="getLatestCreditAnalysis")
async def get_latest_credit_analysis(
    case_id: CaseIdPath, user: User, session: Session, cfg: Config
) -> CreditAnalysisOut:
    """Scores and the representative score with its method, tradelines with utilization and late
    payments, inquiries with their matches, derogatory items, alerts first, flags, the template
    summary, and every figure with its working."""
    await _visible(session, user, case_id)
    run = await credit_runs.latest_run(session, case_id)
    if run is None:
        raise ApiError(404, "not_found", "No credit analysis has been run for this case")
    view = await credit_runs.load_view(session, run)
    return analysis_from_view(view, cfg.thresholds.credit_score_method.value)

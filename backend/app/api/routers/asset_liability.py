"""Asset and liability analysis: the loan scenario, run it, read it, correct a line or a debt.

Feature Design 3.7.

Every endpoint needs a logged-in user and a case that user may see (otherwise 404, like the other
case routers). Running is a background job (the client polls ``GET /jobs/{id}``); the analysis
itself is plain code in ``app.services.assets``. A correction recalculates at once, with no AI call,
keeps what the system decided beside it and writes an audit event.

The contract has no entries for these yet; the paths follow the Feature Design where it names them
and ``docs/contract-proposal-d4.md`` where it does not (the two PATCH routes).
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CaseIdPath, case_not_found, get_current_user, require_roles
from app.api.errors import ApiError
from app.api.schemas.assets import (
    AssetAnalysisOut,
    AssetRunAccepted,
    LoanScenarioIn,
    LoanScenarioOut,
    ObligationReviewIn,
    TransactionReviewIn,
    analysis_from_view,
    scenario_from_row,
)
from app.api.schemas.jobs import JobOut
from app.db.enums import Role
from app.db.session import get_session
from app.services import asset_runs, loan_scenarios
from app.services import cases as case_service
from app.services.documents import UploadFailedError
from app.services.queue import JobQueue, get_queue
from app.services.security import CurrentUser

router = APIRouter(
    prefix="/cases/{case_id}",
    tags=["assets"],
    dependencies=[Depends(require_roles(Role.UNDERWRITER, Role.LM_SPECIALIST, Role.ADMIN))],
)

User = Annotated[CurrentUser, Depends(get_current_user)]
Session = Annotated[AsyncSession, Depends(get_session)]
Queue = Annotated[JobQueue, Depends(get_queue)]


async def _visible(session: AsyncSession, user: CurrentUser, case_id: uuid.UUID) -> None:
    if await case_service.get_case(session, user.role, case_id) is None:
        raise case_not_found()


def _id(value: str, what: str) -> uuid.UUID:
    try:
        return uuid.UUID(value)
    except ValueError:
        raise ApiError(404, "not_found", f"{what} not found") from None


# --- the loan scenario ----------------------------------------------------------------------


@router.put("/loan-scenario", response_model=LoanScenarioOut, operation_id="putLoanScenario")
async def put_loan_scenario(
    case_id: CaseIdPath, body: LoanScenarioIn, user: User, session: Session
) -> LoanScenarioOut:
    """Enter the sample loan by hand, or replace it (the old values go in the audit event)."""
    await _visible(session, user, case_id)
    try:
        row = await loan_scenarios.put_scenario(
            session, user, case_id, loan_scenarios.ScenarioValues(**body.model_dump())
        )
    except loan_scenarios.ScenarioError as exc:
        raise ApiError(422, exc.code, exc.message) from None
    await session.commit()
    return scenario_from_row(row)


@router.get("/loan-scenario", response_model=LoanScenarioOut, operation_id="getLoanScenario")
async def get_loan_scenario(case_id: CaseIdPath, user: User, session: Session) -> LoanScenarioOut:
    await _visible(session, user, case_id)
    row = await loan_scenarios.get_scenario(session, case_id)
    if row is None:
        raise ApiError(404, "not_found", "No loan scenario has been entered for this case")
    return scenario_from_row(row)


# --- the analysis ---------------------------------------------------------------------------


@router.post(
    "/asset-liability",
    status_code=202,
    response_model=AssetRunAccepted,
    operation_id="runAssetLiabilityAnalysis",
)
async def run_asset_liability(
    case_id: CaseIdPath, user: User, session: Session, queue: Queue
) -> AssetRunAccepted:
    """Queue an analysis of the case's statements. Poll the job, then read ``/latest``."""
    await _visible(session, user, case_id)
    try:
        run, job = await asset_runs.start_run(session, queue, user, case_id)
    except UploadFailedError as exc:
        raise ApiError(503, exc.kind, exc.message) from None
    return AssetRunAccepted(job=JobOut.model_validate(job), analysis_id=run.id)


@router.get(
    "/asset-liability/latest",
    response_model=AssetAnalysisOut,
    operation_id="getLatestAssetLiabilityAnalysis",
)
async def get_latest_asset_liability(
    case_id: CaseIdPath, user: User, session: Session
) -> AssetAnalysisOut:
    """The newest analysis: the figures with their working, the debts, the labelled lines, flags."""
    await _visible(session, user, case_id)
    run = await asset_runs.latest_run(session, case_id)
    if run is None:
        raise ApiError(404, "not_found", "No asset analysis has been run for this case")
    return analysis_from_view(await asset_runs.load_view(session, run))


@router.patch(
    "/asset-liability/latest/transactions/{transaction_id}",
    response_model=AssetAnalysisOut,
    operation_id="reviewTransaction",
)
async def review_transaction(
    case_id: CaseIdPath,
    transaction_id: str,
    body: TransactionReviewIn,
    user: User,
    session: Session,
) -> AssetAnalysisOut:
    """Give a line another category, or mark a deposit as sourced, with a reason."""
    await _visible(session, user, case_id)
    wanted = _id(transaction_id, "Transaction")
    try:
        if body.category is not None:
            view = await asset_runs.reclassify_transaction(
                session, user, case_id, wanted, category=body.category, reason=body.reason
            )
        else:
            assert body.sourced is not None
            view = await asset_runs.set_deposit_sourced(
                session, user, case_id, wanted, sourced=body.sourced, note=body.reason
            )
    except asset_runs.AssetError as exc:
        raise ApiError(exc.status, exc.code, exc.message) from None
    return analysis_from_view(view)


@router.patch(
    "/asset-liability/latest/obligations/{obligation_id}",
    response_model=AssetAnalysisOut,
    operation_id="reviewObligation",
)
async def review_obligation(
    case_id: CaseIdPath,
    obligation_id: str,
    body: ObligationReviewIn,
    user: User,
    session: Session,
) -> AssetAnalysisOut:
    """Include a debt in the DTI or leave it out, with a reason. The ratios recalculate at once."""
    await _visible(session, user, case_id)
    wanted = _id(obligation_id, "Obligation")
    try:
        view = await asset_runs.set_obligation_counted(
            session, user, case_id, wanted, counts=body.counts_toward_dti, reason=body.reason
        )
    except asset_runs.AssetError as exc:
        raise ApiError(exc.status, exc.code, exc.message) from None
    return analysis_from_view(view)

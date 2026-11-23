"""The loss mitigation recommendation: read the waterfall, override a condition, sign off (FD 8.7).

Reading needs a logged-in user and a case that user may see (otherwise 404). Overriding and signing
off are for the loss mitigation specialist only: the underwriter cannot see a Pillar 2 case (404)
and the administrator, who maintains the rule set and makes no case decisions, gets 403. Starting
the evaluation (``POST``), the rules engine and the agents come with D7 and D8.

The contract has no entries for these yet; ``docs/contract-proposal-d4.md`` has the YAML.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CaseIdPath, case_not_found, get_current_user, require_roles
from app.api.errors import ApiError
from app.api.schemas.reports import (
    LmRecommendationOut,
    OverrideIn,
    SignOffIn,
    SignOffResult,
    recommendation_from_view,
    sign_off_from_row,
)
from app.db.enums import ReportKind, Role, WaterfallStatus
from app.db.session import get_session
from app.services import cases as case_service
from app.services import reports, review_conditions
from app.services.security import CurrentUser

router = APIRouter(prefix="/cases/{case_id}/lm-recommendation", tags=["lm-recommendation"])

User = Annotated[CurrentUser, Depends(get_current_user)]
Session = Annotated[AsyncSession, Depends(get_session)]
Reader = Depends(require_roles(Role.UNDERWRITER, Role.LM_SPECIALIST, Role.ADMIN))
Reviewer = Depends(require_roles(Role.LM_SPECIALIST))


async def _visible(session: AsyncSession, user: CurrentUser, case_id: uuid.UUID) -> None:
    if await case_service.get_case(session, user.role, case_id) is None:
        raise case_not_found()


@router.get(
    "/latest",
    response_model=LmRecommendationOut,
    operation_id="getLatestLmRecommendation",
    dependencies=[Reader],
)
async def get_latest_lm_recommendation(
    case_id: CaseIdPath, user: User, session: Session
) -> LmRecommendationOut:
    """The waterfall (each option with its status and conditions), the lender view with its
    working, the rule set with its banner, any overrides, and the report once there is one."""
    await _visible(session, user, case_id)
    run = await reports.latest_waterfall_run(session, case_id)
    if run is None:
        raise ApiError(404, "not_found", "No recommendation has been made for this case")
    return recommendation_from_view(await reports.load_waterfall_view(session, run))


@router.put(
    "/latest/conditions/{condition_id}/override",
    response_model=LmRecommendationOut,
    operation_id="overrideLmCondition",
    dependencies=[Reviewer],
)
async def override_condition(
    case_id: CaseIdPath, condition_id: str, body: OverrideIn, user: User, session: Session
) -> LmRecommendationOut:
    """Override a condition, with a reason. The statuses recompute at once; the rules' own status
    stays beside the override. Choosing the status the rules found removes it."""
    await _visible(session, user, case_id)
    try:
        view = await review_conditions.override_condition(
            session,
            user,
            case_id,
            condition_id,
            status=WaterfallStatus(body.status),
            reason=body.reason,
        )
    except review_conditions.ReviewError as exc:
        raise ApiError(exc.status, exc.code, exc.message) from None
    return recommendation_from_view(view)


@router.post(
    "/latest/sign-off",
    status_code=201,
    response_model=SignOffResult,
    operation_id="signOffLmRecommendation",
    dependencies=[Reviewer],
)
async def sign_off(
    case_id: CaseIdPath, body: SignOffIn, user: User, session: Session
) -> SignOffResult:
    """Records a review. Not a decision."""
    await _visible(session, user, case_id)
    try:
        record, extra = await review_conditions.sign_off(
            session, user, case_id, ReportKind.LM_RECOMMENDATION, note=body.note
        )
    except review_conditions.ReviewError as exc:
        raise ApiError(exc.status, exc.code, exc.message) from None
    report = await reports.latest_report(session, case_id, ReportKind.LM_RECOMMENDATION)
    assert report is not None
    return SignOffResult(
        sign_off=sign_off_from_row(record),
        report_status=report.status,
        pending_conditions=extra["pending_conditions"],
    )

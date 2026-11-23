"""The underwriting report: read it, review its conditions, sign off (Feature Design 6.7).

Reading needs a logged-in user and a case that user may see (otherwise 404). Reviewing is for the
underwriter only: the loss mitigation specialist cannot see a Pillar 1 case at all (404), and the
administrator, who maintains settings and makes no case decisions, gets 403. The agents that write
the report (start the workflow, re-run one agent) are Arindam's and are not here.

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
    ConditionAddIn,
    ConditionDecisionIn,
    SignOffIn,
    SignOffResult,
    UnderwritingReportOut,
    report_from_view,
    sign_off_from_row,
)
from app.db.enums import ConditionDecision, ReportKind, Role
from app.db.session import get_session
from app.services import cases as case_service
from app.services import reports, review_conditions
from app.services.security import CurrentUser

router = APIRouter(prefix="/cases/{case_id}/underwriting-report", tags=["underwriting"])

User = Annotated[CurrentUser, Depends(get_current_user)]
Session = Annotated[AsyncSession, Depends(get_session)]
Reader = Depends(require_roles(Role.UNDERWRITER, Role.LM_SPECIALIST, Role.ADMIN))
Reviewer = Depends(require_roles(Role.UNDERWRITER))


async def _visible(session: AsyncSession, user: CurrentUser, case_id: uuid.UUID) -> None:
    if await case_service.get_case(session, user.role, case_id) is None:
        raise case_not_found()


def _fail(exc: review_conditions.ReviewError) -> ApiError:
    return ApiError(exc.status, exc.code, exc.message)


@router.get(
    "/latest",
    response_model=UnderwritingReportOut,
    operation_id="getLatestUnderwritingReport",
    dependencies=[Reader],
)
async def get_latest_underwriting_report(
    case_id: CaseIdPath, user: User, session: Session
) -> UnderwritingReportOut:
    """The newest report: findings, suggested conditions with the review so far, the agents' run
    log and the sign-off record."""
    await _visible(session, user, case_id)
    report = await reports.latest_report(session, case_id, ReportKind.UNDERWRITING)
    if report is None:
        raise ApiError(404, "not_found", "No underwriting report has been made for this case")
    return report_from_view(await reports.load_report_view(session, report))


@router.patch(
    "/latest/conditions/{condition_id}",
    response_model=UnderwritingReportOut,
    operation_id="reviewUnderwritingCondition",
    dependencies=[Reviewer],
)
async def review_condition(
    case_id: CaseIdPath,
    condition_id: str,
    body: ConditionDecisionIn,
    user: User,
    session: Session,
) -> UnderwritingReportOut:
    """Accept, edit or reject a suggested condition. The agents' text is kept beside an edit."""
    await _visible(session, user, case_id)
    try:
        wanted = uuid.UUID(condition_id)
    except ValueError:
        raise ApiError(404, "not_found", "Condition not found") from None
    try:
        view = await review_conditions.decide_condition(
            session,
            user,
            case_id,
            wanted,
            decision=ConditionDecision(body.decision),
            edited_text=body.edited_text,
            reason=body.reason,
        )
    except review_conditions.ReviewError as exc:
        raise _fail(exc) from None
    return report_from_view(view)


@router.post(
    "/latest/conditions",
    status_code=201,
    response_model=UnderwritingReportOut,
    operation_id="addUnderwritingCondition",
    dependencies=[Reviewer],
)
async def add_condition(
    case_id: CaseIdPath, body: ConditionAddIn, user: User, session: Session
) -> UnderwritingReportOut:
    """Add a condition of your own to the report."""
    await _visible(session, user, case_id)
    try:
        view = await review_conditions.add_condition(
            session, user, case_id, text=body.text, priority=body.priority
        )
    except review_conditions.ReviewError as exc:
        raise _fail(exc) from None
    return report_from_view(view)


@router.post(
    "/latest/sign-off",
    status_code=201,
    response_model=SignOffResult,
    operation_id="signOffUnderwritingReport",
    dependencies=[Reviewer],
)
async def sign_off(
    case_id: CaseIdPath, body: SignOffIn, user: User, session: Session
) -> SignOffResult:
    """Records a review. Not a decision."""
    await _visible(session, user, case_id)
    try:
        record, extra = await review_conditions.sign_off(
            session, user, case_id, ReportKind.UNDERWRITING, note=body.note
        )
    except review_conditions.ReviewError as exc:
        raise _fail(exc) from None
    report = await reports.latest_report(session, case_id, ReportKind.UNDERWRITING)
    assert report is not None
    return SignOffResult(
        sign_off=sign_off_from_row(record),
        report_status=report.status,
        pending_conditions=extra["pending_conditions"],
    )

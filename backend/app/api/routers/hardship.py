"""Hardship assessment: read a letter, confirm the reading, read and adjust the budget (FD 7.7).

Every endpoint needs a logged-in user and a case that user may see (otherwise 404, like the other
case routers), so a Pillar 1 case is invisible to the loss-mitigation specialist and the other way
round. Reading the letter is a background job (the client polls ``GET /jobs/{id}``): the model reads
the letter and labels the bank statement lines, and everything else, the budget and its measures,
is plain code. Confirming the reading and adjusting a budget line are for the loss mitigation
specialist only (the administrator makes no case decisions, so gets 403); both recalculate at once
with no model call, keep what the system produced beside the change, and write an audit event.

The contract has no hardship endpoints yet (only a TODO that spells the path ``/hardship/profile``).
These follow the Feature Design's paths until it does; ``docs/contract-proposal-d4.md`` has
the YAML.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CaseIdPath, case_not_found, get_current_user, require_roles
from app.api.errors import ApiError
from app.api.schemas.hardship import (
    BudgetAdjustIn,
    ConfirmationsIn,
    HardshipAssessmentOut,
    HardshipRunAccepted,
    assessment_from_view,
)
from app.api.schemas.jobs import JobOut
from app.db.enums import Role
from app.db.session import get_session
from app.prompts.schemas.hardship import HardshipConfig
from app.services import budget_runs, hardship, hardship_runs
from app.services import cases as case_service
from app.services.documents import UploadFailedError
from app.services.queue import JobQueue, get_queue
from app.services.security import CurrentUser

router = APIRouter(
    prefix="/cases/{case_id}/hardship-assessment",
    tags=["hardship"],
    dependencies=[Depends(require_roles(Role.UNDERWRITER, Role.LM_SPECIALIST, Role.ADMIN))],
)
Reviewer = Depends(require_roles(Role.LM_SPECIALIST))

User = Annotated[CurrentUser, Depends(get_current_user)]
Session = Annotated[AsyncSession, Depends(get_session)]
Queue = Annotated[JobQueue, Depends(get_queue)]
Config = Annotated[HardshipConfig, Depends(hardship_runs.get_hardship_config)]


async def _visible(session: AsyncSession, user: CurrentUser, case_id: uuid.UUID) -> None:
    if await case_service.get_case(session, user.role, case_id) is None:
        raise case_not_found()


async def _assessment(
    session: AsyncSession, case_id: uuid.UUID, config: HardshipConfig
) -> HardshipAssessmentOut:
    view = await hardship_runs.latest(session, case_id)
    if view is None:
        raise ApiError(404, "not_found", "No hardship assessment has been made for this case")
    return assessment_from_view(view, config, await budget_runs.load_view(session, view.run))


@router.post(
    "", status_code=202, response_model=HardshipRunAccepted, operation_id="runHardshipReading"
)
async def run_hardship_reading(
    case_id: CaseIdPath, user: User, session: Session, queue: Queue
) -> HardshipRunAccepted:
    """Queue a reading of the case's hardship letter. Poll the job, then read ``/latest``. The
    earlier reading, such as the seeded sample, stays as history."""
    await _visible(session, user, case_id)
    try:
        job = await hardship.start_reading(session, queue, user, case_id)
    except hardship.HardshipError as exc:
        raise ApiError(exc.status, exc.code, exc.message) from None
    except UploadFailedError as exc:
        raise ApiError(503, exc.kind, exc.message) from None
    return HardshipRunAccepted(job=JobOut.model_validate(job))


@router.get(
    "/latest", response_model=HardshipAssessmentOut, operation_id="getLatestHardshipAssessment"
)
async def get_latest_hardship_assessment(
    case_id: CaseIdPath, user: User, session: Session, config: Config
) -> HardshipAssessmentOut:
    """The newest profile with each item's quote, lines and check, the specialist's confirmations,
    and the budget with its measures, consistency checks and flags."""
    await _visible(session, user, case_id)
    return await _assessment(session, case_id, config)


@router.put(
    "/latest/confirmations",
    response_model=HardshipAssessmentOut,
    operation_id="confirmHardshipItems",
    dependencies=[Reviewer],
)
async def confirm_hardship_items(
    case_id: CaseIdPath, body: ConfirmationsIn, user: User, session: Session, config: Config
) -> HardshipAssessmentOut:
    """Confirm the reading's reason, onset, duration or intent, or correct it with a reason. The
    value as read stays beside the confirmation (labelled "reviewer-confirmed")."""
    await _visible(session, user, case_id)
    given = {
        item: hardship.ItemConfirmation(sent.value, sent.reason)
        for item in hardship.ITEMS
        if (sent := getattr(body, item)) is not None
    }
    try:
        view = await hardship.confirm_items(session, user, case_id, given, config=config)
    except hardship.HardshipError as exc:
        raise ApiError(exc.status, exc.code, exc.message) from None
    return assessment_from_view(view, config, await budget_runs.load_view(session, view.run))


@router.patch(
    "/latest/budget/{line_id}",
    response_model=HardshipAssessmentOut,
    operation_id="adjustBudgetLine",
    dependencies=[Reviewer],
)
async def adjust_budget_line(
    case_id: CaseIdPath,
    line_id: str,
    body: BudgetAdjustIn,
    user: User,
    session: Session,
    config: Config,
) -> HardshipAssessmentOut:
    """Count a different observed amount for a budget line (for example, part of it was one-off),
    with a reason, or clear an earlier adjustment. The measures update at once, with no model."""
    await _visible(session, user, case_id)
    try:
        wanted = uuid.UUID(line_id)
    except ValueError:
        raise ApiError(404, "not_found", "Budget line not found") from None
    view = await hardship_runs.latest(session, case_id)
    if view is None:
        raise ApiError(404, "not_found", "No hardship assessment has been made for this case")
    try:
        await budget_runs.adjust_line(
            session,
            user,
            case_id,
            view.run,
            wanted,
            amount=body.adjusted_amount,
            reason=body.reason,
        )
    except budget_runs.BudgetError as exc:
        raise ApiError(exc.status, exc.code, exc.message) from None
    return await _assessment(session, case_id, config)

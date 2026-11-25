"""A person reviews a report: accept, edit or reject a condition, add their own, override a
waterfall condition, and sign off (Feature Design 6.2, 6.7, 8.2 and 8.7).

Nothing a person does overwrites what the system produced (rule 6): a condition keeps the text the
agents wrote beside the reviewer's edit, an overridden waterfall condition keeps the rules' own
status beside the override, and each action writes an audit event with who, when and why. None of it
is a decision about the loan (rule 3): a sign-off records that a person reviewed a version of the
report, and the response says so.

Who may act is checked here as well as in the routers: only the underwriter reviews a Pillar 1
report, only the loss mitigation specialist a Pillar 2 one, and the administrator reviews neither.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.enums import (
    ConditionDecision,
    ConditionSource,
    ReportKind,
    ReportStatus,
    ReviewPriority,
    Role,
    WaterfallStatus,
)
from app.db.models import Condition, Report, SignOff, WaterfallResult
from app.services import audit, reports
from app.services.security import CurrentUser
from app.services.waterfall_status import effective_status, override_summary, recompute

SIGN_OFF_STATEMENT = "Records a review. Not a decision."
REVIEWER_FOR: dict[ReportKind, Role] = {
    ReportKind.UNDERWRITING: Role.UNDERWRITER,
    ReportKind.LM_RECOMMENDATION: Role.LM_SPECIALIST,
}


class ReviewError(Exception):
    """A review action that cannot be honoured. ``status`` and ``code`` are for the API."""

    def __init__(self, status: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status, self.code, self.message = status, code, message


def _now() -> datetime:
    return datetime.now(UTC)


def _check_role(user: CurrentUser, kind: ReportKind) -> None:
    if user.role != REVIEWER_FOR[kind]:
        raise ReviewError(403, "forbidden", "Your role cannot review this report")


async def _latest(session: AsyncSession, case_id: uuid.UUID, kind: ReportKind) -> Report:
    report = await reports.latest_report(session, case_id, kind)
    if report is None:
        raise ReviewError(404, "not_found", "No report has been made for this case")
    return report


async def _reviewable_report(session: AsyncSession, case_id: uuid.UUID, kind: ReportKind) -> Report:
    """The report a sign-off is about. For the recommendation it must belong to the newest
    evaluation: an older run's report (such as the seeded sample) says nothing about the waterfall
    the reviewer is looking at, and the rules alone do not write a report (the agents do)."""
    if kind != ReportKind.LM_RECOMMENDATION:
        return await _latest(session, case_id, kind)
    run = await reports.latest_waterfall_run(session, case_id)
    if run is None:
        raise ReviewError(404, "not_found", "No recommendation has been made for this case")
    report = await session.scalar(
        sa.select(Report).where(Report.run_id == run.id).order_by(Report.version.desc()).limit(1)
    )
    if report is None:
        raise ReviewError(
            409,
            "no_report",
            "The newest evaluation has no report yet, so there is nothing to record a review of.",
        )
    return report


async def _in_review(session: AsyncSession, report: Report) -> dict[str, str]:
    """A review action moves a draft, or a signed-off report that has changed, to in review."""
    before = report.status.value
    if report.status != ReportStatus.IN_REVIEW:
        report.status = ReportStatus.IN_REVIEW
    await session.flush()
    return {"report_status_before": before, "report_status": report.status.value}


# --- conditions of the underwriting report ---------------------------------------------------


async def decide_condition(
    session: AsyncSession,
    user: CurrentUser,
    case_id: uuid.UUID,
    condition_id: uuid.UUID,
    *,
    decision: ConditionDecision,
    edited_text: str | None,
    reason: str | None,
) -> reports.ReportView:
    """Accept, edit or reject a suggested condition. Editing needs the new text and a reason;
    rejecting needs a reason. The agents' text is kept beside the edit."""
    _check_role(user, ReportKind.UNDERWRITING)
    report = await _latest(session, case_id, ReportKind.UNDERWRITING)
    condition = await session.get(Condition, condition_id)
    if condition is None or condition.report_id != report.id:
        owner = await session.get(Report, condition.report_id) if condition else None
        if owner is not None and owner.case_id == case_id:
            raise ReviewError(409, "stale_report", "A newer report has replaced this one.")
        raise ReviewError(404, "not_found", "Condition not found")
    if decision == ConditionDecision.PENDING:
        raise ReviewError(422, "invalid_decision", "Choose accepted, edited or rejected.")
    reason = (reason or "").strip() or None
    edited_text = (edited_text or "").strip() or None
    if decision == ConditionDecision.EDITED and not (edited_text and reason):
        raise ReviewError(422, "invalid_decision", "An edit needs the new text and a reason.")
    if decision == ConditionDecision.REJECTED and not reason:
        raise ReviewError(422, "invalid_decision", "A rejection needs a reason.")

    before = {
        "decision": condition.decision.value,
        "edited_text": condition.edited_text,
        "reason": condition.reason,
    }
    condition.decision = decision
    condition.edited_text = edited_text if decision == ConditionDecision.EDITED else None
    condition.reason = reason
    condition.decided_by, condition.decided_at = uuid.UUID(user.id), _now()
    await session.flush()
    moved = await _in_review(session, report)
    await audit.record(
        session,
        actor_id=uuid.UUID(user.id),
        role=user.role.value,
        action=f"underwriting.condition_{decision.value}",
        entity_type="condition",
        entity_id=condition.id,
        case_id=case_id,
        before=before,
        after={
            "decision": decision.value,
            "edited_text": condition.edited_text,
            "original_text": condition.text,
            **moved,
        },
        reason=reason,
    )
    await session.commit()
    return await reports.load_report_view(session, report)


async def add_condition(
    session: AsyncSession,
    user: CurrentUser,
    case_id: uuid.UUID,
    *,
    text: str,
    priority: ReviewPriority,
) -> reports.ReportView:
    """Add a condition of the reviewer's own. It is the reviewer's decision to make, so it is
    recorded as accepted by them, with ``source`` ``user``."""
    _check_role(user, ReportKind.UNDERWRITING)
    report = await _latest(session, case_id, ReportKind.UNDERWRITING)
    text = text.strip()
    if not text:
        raise ReviewError(422, "invalid_condition", "A condition needs text.")
    last = await session.scalar(
        sa.select(sa.func.max(Condition.position)).where(Condition.report_id == report.id)
    )
    condition = Condition(
        report_id=report.id,
        position=(last or 0) + 1,
        text=text,
        priority=priority,
        source=ConditionSource.USER,
        decision=ConditionDecision.ACCEPTED,
        decided_by=uuid.UUID(user.id),
        decided_at=_now(),
    )
    session.add(condition)
    await session.flush()
    moved = await _in_review(session, report)
    await audit.record(
        session,
        actor_id=uuid.UUID(user.id),
        role=user.role.value,
        action="underwriting.condition_added",
        entity_type="condition",
        entity_id=condition.id,
        case_id=case_id,
        after={"text": text, "priority": priority.value, "source": "user", **moved},
    )
    await session.commit()
    return await reports.load_report_view(session, report)


# --- waterfall conditions of the loss mitigation recommendation -----------------------------


async def override_condition(
    session: AsyncSession,
    user: CurrentUser,
    case_id: uuid.UUID,
    condition_id: str,
    *,
    status: WaterfallStatus,
    reason: str,
) -> reports.WaterfallView:
    """Override one waterfall condition with a reason. The rules' status stays beside it, the
    option statuses recompute at once, and the override stays visible. Choosing the status the
    rules found removes the override."""
    _check_role(user, ReportKind.LM_RECOMMENDATION)
    run = await reports.latest_waterfall_run(session, case_id)
    if run is None:
        raise ReviewError(404, "not_found", "No recommendation has been made for this case")
    reason = reason.strip()
    if not reason:
        raise ReviewError(422, "invalid_override", "An override needs a reason.")
    rows = list(
        (
            await session.execute(
                sa.select(WaterfallResult)
                .where(WaterfallResult.run_id == run.id)
                .order_by(WaterfallResult.order_no)
            )
        )
        .scalars()
        .all()
    )
    target = next((r for r in rows if any(c["id"] == condition_id for c in r.conditions)), None)
    if target is None:
        raise ReviewError(404, "not_found", "Condition not found")
    condition = next(c for c in target.conditions if c["id"] == condition_id)
    if condition.get("derived"):
        raise ReviewError(
            422, "derived_condition", "This condition follows from the earlier options."
        )
    if status in (WaterfallStatus.NOT_REACHED,):
        raise ReviewError(
            422, "invalid_override", "A condition cannot be overridden to not reached."
        )

    before = {
        "status": condition["status"],
        "effective_status": effective_status(condition),
        "option_status": target.status.value,
    }
    now, actor = _now(), uuid.UUID(user.id)
    fresh = [dict(c) for c in target.conditions]
    changed = next(c for c in fresh if c["id"] == condition_id)
    if status.value == changed["status"]:
        changed.pop("override", None)
    else:
        changed["override"] = {
            "status": status.value,
            "reason": reason,
            "by": str(actor),
            "at": now.isoformat(),
        }
    plan = recompute([fresh if r is target else list(r.conditions) for r in rows])
    for row, (new_status, conditions) in zip(rows, plan, strict=True):
        row.status = WaterfallStatus(new_status)
        row.conditions = conditions
        row.overridden, latest_reason, by, at = override_summary(conditions)
        row.override_reason = latest_reason
        row.overridden_by = uuid.UUID(by) if by else None
        row.overridden_at = datetime.fromisoformat(at) if at else None
    await session.flush()
    report = await session.scalar(
        sa.select(Report).where(Report.run_id == run.id).order_by(Report.version.desc()).limit(1)
    )
    moved = await _in_review(session, report) if report else {}
    await audit.record(
        session,
        actor_id=actor,
        role=user.role.value,
        action="lm.condition_overridden"
        if status.value != changed["status"]
        else "lm.condition_override_removed",
        entity_type="waterfall_condition",
        entity_id=target.id,
        case_id=case_id,
        before=before,
        after={
            "condition": condition_id,
            "system_status": changed["status"],
            "status": status.value,
            "option": target.option.value,
            "option_status": target.status.value,
            "option_system_status": target.original_status.value,
            **moved,
        },
        reason=reason,
    )
    await session.commit()
    return await reports.load_waterfall_view(session, run)


# --- sign-off --------------------------------------------------------------------------------


async def sign_off(
    session: AsyncSession,
    user: CurrentUser,
    case_id: uuid.UUID,
    kind: ReportKind,
    *,
    note: str | None,
) -> tuple[SignOff, dict[str, Any]]:
    """Record that this person reviewed the newest version of the report. Not a decision."""
    _check_role(user, kind)
    report = await _reviewable_report(session, case_id, kind)
    actor = uuid.UUID(user.id)
    already = await session.scalar(
        sa.select(SignOff.id).where(
            SignOff.report_id == report.id,
            SignOff.report_version == report.version,
            SignOff.signed_by == actor,
        )
    )
    if already is not None:
        raise ReviewError(409, "already_signed_off", "You have already recorded a review of this.")
    counts: dict[str, int] = {}
    if kind == ReportKind.UNDERWRITING:
        rows = await session.execute(
            sa.select(Condition.decision, sa.func.count())
            .where(Condition.report_id == report.id)
            .group_by(Condition.decision)
        )
        counts = {d.value: n for d, n in rows.all()}
    record = SignOff(
        report_id=report.id,
        case_id=case_id,
        report_version=report.version,
        signed_by=actor,
        role=user.role.value,
        signed_at=_now(),
        note=(note or "").strip() or None,
    )
    session.add(record)
    before = report.status.value
    report.status = ReportStatus.SIGNED_OFF
    await session.flush()
    await audit.record(
        session,
        actor_id=actor,
        role=user.role.value,
        action="report.signed_off",
        entity_type="report",
        entity_id=report.id,
        case_id=case_id,
        before={"report_status": before},
        after={
            "report_status": report.status.value,
            "report_version": report.version,
            "kind": kind.value,
            "conditions": counts or None,
            "statement": SIGN_OFF_STATEMENT,
        },
        reason=record.note,
    )
    await session.commit()
    return record, {"pending_conditions": counts.get("pending", 0)}

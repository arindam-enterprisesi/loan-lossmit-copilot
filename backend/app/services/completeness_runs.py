"""Completeness runs: run a checklist over a case, read the latest result, override an item.

``app.services.completeness`` decides every status (pure). This is the database side. A run is an
``analysis_runs`` row (feature ``completeness``) with one ``completeness_results`` row; a new run
never edits an old one (rule 6), so "latest" is the newest.

An override is a person's, with a written reason. It sits beside the computed status of its item
and never replaces it, counts as satisfied for the overall status, can be cleared, and is audited.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.enums import AnalysisFeature, AnalysisStatus, CompletenessOverall
from app.db.models import AnalysisRun, Case, CompletenessResult
from app.services import audit
from app.services.analysis_config import AnalysisConfig
from app.services.case_facts import load_case_documents
from app.services.completeness import ItemResult, Profile, evaluate, overall_of
from app.services.config_versions import record_config_versions
from app.services.security import CurrentUser


class CompletenessError(Exception):
    """A request the check cannot honour. ``status`` and ``code`` are for the API."""

    def __init__(self, status: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status, self.code, self.message = status, code, message


@dataclass
class CompletenessView:
    run: AnalysisRun
    result: CompletenessResult

    def items(self) -> list[ItemResult]:
        return [ItemResult.from_json(i) for i in self.result.items]

    @property
    def checklist_id(self) -> str:
        return str(self.run.config_versions["checklist"]["name"])


def _now() -> datetime:
    return datetime.now(UTC)


def _checked_checklist(case: Case, checklist_id: str, cfg: AnalysisConfig) -> None:
    checklist = cfg.checklists.get(checklist_id)
    if checklist is None:
        raise CompletenessError(422, "unknown_checklist", f"There is no checklist {checklist_id}.")
    if checklist.pillar != case.pillar.value:
        raise CompletenessError(
            422, "wrong_checklist", f"{checklist.title} is for {checklist.pillar} cases."
        )
    employment = case.employment_type.value if case.employment_type else None
    if employment is not None and employment not in checklist.employment_types:
        raise CompletenessError(
            422, "wrong_checklist", f"{checklist.title} is not for {employment} borrowers."
        )


async def run_completeness(
    session: AsyncSession,
    user: CurrentUser,
    case: Case,
    checklist_id: str,
    cfg: AnalysisConfig,
) -> CompletenessView:
    """Check the case's documents against a checklist, store the result and return it."""
    _checked_checklist(case, checklist_id, cfg)
    if not case.borrower_names or case.reference_date is None:
        raise CompletenessError(
            422,
            "profile_required",
            "Enter the borrower names and the reference date on the case profile first.",
        )
    checklist = cfg.checklists.checklists[checklist_id]
    documents = await load_case_documents(session, case.id)
    outcome = evaluate(
        checklist,
        cfg.checklists,
        Profile(list(case.borrower_names), case.reference_date),
        documents,
    )

    uses = cfg.uses(checklist_id=checklist_id)
    await record_config_versions(session, uses)
    now = _now()
    run = AnalysisRun(
        case_id=case.id,
        feature=AnalysisFeature.COMPLETENESS,
        status=AnalysisStatus.SUCCEEDED,
        config_versions=cfg.snapshot(uses),
        started_at=now,
        finished_at=now,
        created_by=uuid.UUID(user.id),
    )
    session.add(run)
    await session.flush()
    result = CompletenessResult(
        run_id=run.id,
        case_id=case.id,
        items=[item.as_json() for item in outcome.items],
        overall_status=CompletenessOverall(outcome.overall),
    )
    session.add(result)
    await session.flush()
    counts: dict[str, int] = {}
    for item in outcome.items:
        counts[item.status] = counts.get(item.status, 0) + 1
    await audit.record(
        session,
        actor_id=uuid.UUID(user.id),
        role=user.role.value,
        action="completeness.run",
        entity_type="analysis_run",
        entity_id=run.id,
        case_id=case.id,
        after={
            "checklist_id": checklist_id,
            "overall": outcome.overall,
            "items": counts,
            "documents": len([d for d in documents if d.usable]),
            "config_versions": run.config_versions,
        },
    )
    await session.commit()
    return CompletenessView(run, result)


async def latest_view(session: AsyncSession, case_id: uuid.UUID) -> CompletenessView | None:
    """The newest completeness result of the case."""
    row = (
        await session.execute(
            sa.select(AnalysisRun, CompletenessResult)
            .join(CompletenessResult, CompletenessResult.run_id == AnalysisRun.id)
            .where(
                AnalysisRun.case_id == case_id,
                AnalysisRun.feature == AnalysisFeature.COMPLETENESS,
            )
            .order_by(AnalysisRun.started_at.desc(), AnalysisRun.id.desc())
            .limit(1)
        )
    ).first()
    return CompletenessView(row[0], row[1]) if row else None


async def set_override(
    session: AsyncSession,
    user: CurrentUser,
    case_id: uuid.UUID,
    item_id: str,
    *,
    action: Literal["override", "clear"],
    reason: str | None,
) -> CompletenessView:
    """Override an item with a written reason, or clear an override. Audited; keeps the original."""
    view = await latest_view(session, case_id)
    if view is None:
        raise CompletenessError(
            404, "not_found", "No completeness check has been run for this case"
        )
    items = view.items()
    item = next((i for i in items if i.item_id == item_id), None)
    if item is None:
        raise CompletenessError(404, "not_found", "Checklist item not found")

    before: dict[str, Any] = {
        "item_id": item_id,
        "computed_status": item.status,
        "override": item.override,
        "overall": view.result.overall_status.value,
    }
    if action == "override":
        if item.override is not None:
            raise CompletenessError(409, "already_overridden", "This item is already overridden.")
        if item.status == "satisfied":
            raise CompletenessError(409, "nothing_to_override", "This item is already satisfied.")
        item.override = {"reason": reason, "by": user.id, "at": _now().isoformat()}
    else:
        if item.override is None:
            raise CompletenessError(409, "no_override", "This item has no override to clear.")
        item.override = None

    view.result.items = [i.as_json() for i in items]  # a new list, so the change is saved
    view.result.overall_status = CompletenessOverall(overall_of(items))
    view.result.updated_by, view.result.updated_at = uuid.UUID(user.id), _now()
    await audit.record(
        session,
        actor_id=uuid.UUID(user.id),
        role=user.role.value,
        action="completeness.item_overridden"
        if action == "override"
        else "completeness.override_cleared",
        entity_type="completeness_item",
        entity_id=view.result.id,
        case_id=case_id,
        before=before,
        after={
            "item_id": item_id,
            "computed_status": item.status,
            "override": item.override,
            "overall": view.result.overall_status.value,
        },
        reason=reason,
    )
    await session.commit()
    return view

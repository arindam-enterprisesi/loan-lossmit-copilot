"""Completeness as the API sends it (contracts/openapi.yaml: ``CompletenessResult``).

The contract's item statuses are satisfied, partial, missing and overridden, and its overall status
is complete or incomplete. The FSD also has "needs review" (a needed field was not found, the owner
is uncertain, a document is future-dated). Until the contract has that value, a needs-review item
is sent as ``partial`` with a "Needs review:" reason, and a needs-review overall as ``incomplete``:
nothing is hidden, and the wording says which it is.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.services.analysis_config import AnalysisConfig
from app.services.completeness import ItemResult
from app.services.completeness_runs import CompletenessView

ItemStatus = Literal["satisfied", "partial", "missing", "overridden"]
NEEDS_REVIEW_PREFIX = "Needs review: "


class CompletenessItemOut(BaseModel):
    item_id: str
    label: str
    status: ItemStatus
    reason: str
    document_ids: list[uuid.UUID]
    override_reason: str | None = None


class CompletenessResultOut(BaseModel):
    id: uuid.UUID
    case_id: uuid.UUID
    checklist_id: str
    checklist_version: str
    checklist_label: Literal["illustrative", "authoritative"]
    overall_status: Literal["complete", "incomplete"]
    items: list[CompletenessItemOut]
    outstanding: list[str]
    run_at: datetime


class CompletenessRunIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    checklist_id: str = Field(min_length=1, max_length=100)


class ItemOverrideIn(BaseModel):
    """Override an item with a written reason, or clear the override."""

    model_config = ConfigDict(extra="forbid")

    action: Literal["override", "clear"]
    reason: str | None = Field(default=None, max_length=500)

    @model_validator(mode="after")
    def _an_override_needs_a_reason(self) -> ItemOverrideIn:
        if self.action == "override":
            self.reason = (self.reason or "").strip()
            if not self.reason:
                raise ValueError("a reason is required to override an item")
        return self


def _item_out(item: ItemResult) -> tuple[CompletenessItemOut, str | None]:
    """The item as the contract has it, and its line in the outstanding list (None if none)."""
    if item.override is not None:
        status: ItemStatus = "overridden"
        reason = item.reason
    elif item.status == "needs_review":
        status, reason = "partial", NEEDS_REVIEW_PREFIX + item.reason
    else:
        status, reason = item.status, item.reason
    out = CompletenessItemOut(
        item_id=item.item_id,
        label=item.label,
        status=status,
        reason=reason,
        document_ids=[uuid.UUID(d) for d in item.document_ids],
        override_reason=item.override["reason"] if item.override else None,
    )
    outstanding = (
        None
        if item.override is not None or item.status == "satisfied"
        else f"{item.label}: {reason}"
    )
    return out, outstanding


def result_from_view(view: CompletenessView, cfg: AnalysisConfig) -> CompletenessResultOut:
    checklist = cfg.checklists.checklists[view.checklist_id]
    shown = [_item_out(item) for item in view.items()]
    return CompletenessResultOut(
        id=view.result.id,
        case_id=view.result.case_id,
        checklist_id=view.checklist_id,
        checklist_version=checklist.version,
        checklist_label=checklist.label,
        overall_status="complete"
        if view.result.overall_status.value == "complete"
        else "incomplete",
        items=[out for out, _ in shown],
        outstanding=[line for _, line in shown if line],
        run_at=view.run.started_at,
    )

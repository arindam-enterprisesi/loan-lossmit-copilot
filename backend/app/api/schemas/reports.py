"""Reports, conditions, the waterfall and sign-off as the API sends them (Feature Design 6.7, 8.7).

Wording is for review: nothing here says a person is approved, denied, offered or eligible (rule 3).
A sign-off carries its own statement, "Records a review. Not a decision.", so no screen can present
it as one. Where a person changed what the system produced, both are sent: the agents' condition
text beside the reviewer's edit, the rules' status beside the override (rule 6).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.api.schemas.assets import CalcOut, calc_from_row
from app.api.schemas.income import exact
from app.api.schemas.jobs import JobOut
from app.db.enums import (
    AgentName,
    AgentRunStatus,
    AnalysisStatus,
    ConditionDecision,
    ConditionSource,
    ReportKind,
    ReportSource,
    ReportStatus,
    ReviewPriority,
    WaterfallOption,
    WaterfallStatus,
)
from app.db.models import AgentRun, Condition, Finding, SignOff, WaterfallResult
from app.services.reports import ReportView, WaterfallView
from app.services.review_conditions import SIGN_OFF_STATEMENT
from app.services.waterfall_status import effective_status

SEEDED_NOTICE = "Seeded sample: written by hand, not by the agents or the rules engine."
ILLUSTRATIVE_BANNER = "Illustrative: not an actual investor's requirements."
FINAL_TERMS = (
    "Final terms are never computed here: to be calculated under the investor's own method."
)


class FindingOut(BaseModel):
    id: uuid.UUID
    priority: ReviewPriority
    title: str
    detail: str
    # Where it came from: calculation names, rule IDs, checklist items, document lines (rule 2).
    evidence: list[dict[str, Any]]


class ConditionOut(BaseModel):
    id: uuid.UUID
    position: int
    # What the agents (or the reviewer, for their own) wrote; never changed.
    text: str
    priority: ReviewPriority
    source: ConditionSource
    decision: ConditionDecision
    edited_text: str | None
    # The text to show: the reviewer's edit when there is one.
    current_text: str
    reason: str | None
    decided_by: uuid.UUID | None
    decided_at: datetime | None


class AgentRunOut(BaseModel):
    id: uuid.UUID
    agent: AgentName
    attempt: int
    status: AgentRunStatus
    provider: str | None
    model: str | None
    prompt_id: str | None
    output: dict[str, Any] | None
    error: str | None
    started_at: datetime | None
    finished_at: datetime | None


class SignOffOut(BaseModel):
    id: uuid.UUID
    report_id: uuid.UUID
    report_version: int
    signed_by: uuid.UUID
    role: str
    signed_at: datetime
    note: str | None
    statement: str = SIGN_OFF_STATEMENT


class ReportOut(BaseModel):
    id: uuid.UUID
    kind: ReportKind
    version: int
    status: ReportStatus
    source: ReportSource
    notice: str | None
    created_at: datetime
    sections: dict[str, Any]
    guardrail_results: dict[str, Any]


class UnderwritingReportOut(BaseModel):
    run_id: uuid.UUID
    run_status: AnalysisStatus
    report: ReportOut
    findings: list[FindingOut]
    conditions: list[ConditionOut]
    agent_runs: list[AgentRunOut]
    sign_offs: list[SignOffOut]


class SignOffResult(BaseModel):
    sign_off: SignOffOut
    report_status: ReportStatus
    # Conditions still undecided when the review was recorded (underwriting only).
    pending_conditions: int


# --- the waterfall ---------------------------------------------------------------------------


class OverrideOut(BaseModel):
    status: WaterfallStatus
    reason: str
    by: uuid.UUID
    at: datetime


class WaterfallConditionOut(BaseModel):
    id: str
    label: str
    expression: str
    values: dict[str, Any]
    passage_id: str | None
    derived: bool
    # Why a condition could not be decided (what is missing, or what a person must confirm), and
    # where each value was read: a document line, a stored calculation or the loan record.
    note: str | None = None
    evidence: list[dict[str, Any]] = Field(default_factory=list)
    # What the rules found, and what counts now (the override, when there is one).
    status: WaterfallStatus
    effective_status: WaterfallStatus
    override: OverrideOut | None


class WaterfallOptionOut(BaseModel):
    option: WaterfallOption
    order_no: int
    status: WaterfallStatus
    original_status: WaterfallStatus
    conditions: list[WaterfallConditionOut]
    overridden: bool
    override_reason: str | None
    overridden_by: uuid.UUID | None
    overridden_at: datetime | None


class LenderViewOut(BaseModel):
    foreclosure_loss: str
    modification_cost: str
    advantage: str
    settings: dict[str, Any]
    figures: list[CalcOut]
    final_terms: str = FINAL_TERMS


class RuleSetOut(BaseModel):
    name: str
    version: str
    label: str
    banner: str | None


class RecommendationRunAccepted(BaseModel):
    job: JobOut


class LmRecommendationOut(BaseModel):
    run_id: uuid.UUID
    run_status: AnalysisStatus
    source: Literal["rules_engine", "seeded_sample"]
    notice: str | None
    rule_set: RuleSetOut | None
    waterfall: list[WaterfallOptionOut]
    lender_view: LenderViewOut | None
    # Null until the agents (or the seeded sample) have written one.
    report: UnderwritingReportOut | None


# --- what a person sends ---------------------------------------------------------------------


def _strip(value: str | None) -> str | None:
    return value.strip() or None if value is not None else None


class ConditionDecisionIn(BaseModel):
    """Accept, edit or reject a suggested condition. An edit needs the new text and a reason; a
    rejection needs a reason."""

    model_config = ConfigDict(extra="forbid")

    decision: Literal["accepted", "edited", "rejected"]
    edited_text: str | None = Field(default=None, max_length=2000)
    reason: str | None = Field(default=None, max_length=500)

    _edited = field_validator("edited_text")(_strip)
    _reason = field_validator("reason")(_strip)

    @model_validator(mode="after")
    def _complete(self) -> ConditionDecisionIn:
        if self.decision == "edited" and not (self.edited_text and self.reason):
            raise ValueError("an edit needs the new text and a reason")
        if self.decision == "rejected" and not self.reason:
            raise ValueError("a rejection needs a reason")
        if self.decision != "edited" and self.edited_text:
            raise ValueError("edited_text is only for an edit")
        return self


class ConditionAddIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str = Field(min_length=1, max_length=2000)
    priority: ReviewPriority = ReviewPriority.ATTENTION

    @field_validator("text")
    @classmethod
    def _text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("a condition needs text")
        return value


class OverrideIn(BaseModel):
    """Override one waterfall condition. The reason is required."""

    model_config = ConfigDict(extra="forbid")

    status: Literal["met", "not_met", "not_evaluable", "needs_confirmation"]
    reason: str = Field(max_length=500)

    @field_validator("reason")
    @classmethod
    def _reason(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("a reason is required")
        return value


class SignOffIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    note: str | None = Field(default=None, max_length=500)


# --- from rows -------------------------------------------------------------------------------


def finding_from_row(row: Finding) -> FindingOut:
    return FindingOut(
        id=row.id,
        priority=row.priority,
        title=row.title,
        detail=row.detail,
        evidence=list(row.evidence or []),
    )


def condition_from_row(row: Condition) -> ConditionOut:
    return ConditionOut(
        id=row.id,
        position=row.position,
        text=row.text,
        priority=row.priority,
        source=row.source,
        decision=row.decision,
        edited_text=row.edited_text,
        current_text=row.edited_text or row.text,
        reason=row.reason,
        decided_by=row.decided_by,
        decided_at=row.decided_at,
    )


def agent_run_from_row(row: AgentRun) -> AgentRunOut:
    return AgentRunOut(
        id=row.id,
        agent=row.agent,
        attempt=row.attempt,
        status=row.status,
        provider=row.provider,
        model=row.model,
        prompt_id=row.prompt_id,
        output=row.output,
        error=row.error,
        started_at=row.started_at,
        finished_at=row.finished_at,
    )


def sign_off_from_row(row: SignOff) -> SignOffOut:
    return SignOffOut(
        id=row.id,
        report_id=row.report_id,
        report_version=row.report_version,
        signed_by=row.signed_by,
        role=row.role,
        signed_at=row.signed_at,
        note=row.note,
    )


def report_from_view(view: ReportView) -> UnderwritingReportOut:
    report = view.report
    return UnderwritingReportOut(
        run_id=view.run.id,
        run_status=view.run.status,
        report=ReportOut(
            id=report.id,
            kind=report.kind,
            version=report.version,
            status=report.status,
            source=report.source,
            notice=SEEDED_NOTICE if report.source == ReportSource.SEEDED_SAMPLE else None,
            created_at=report.created_at,
            sections=report.sections,
            guardrail_results=report.guardrail_results,
        ),
        findings=[finding_from_row(f) for f in view.findings],
        conditions=[condition_from_row(c) for c in view.conditions],
        agent_runs=[agent_run_from_row(a) for a in view.agent_runs],
        sign_offs=[sign_off_from_row(s) for s in view.sign_offs],
    )


def _condition_result(c: dict[str, Any]) -> WaterfallConditionOut:
    override = c.get("override")
    return WaterfallConditionOut(
        id=c["id"],
        label=c["label"],
        expression=c["expression"],
        values=c.get("values", {}),
        passage_id=c.get("passage_id"),
        derived=bool(c.get("derived")),
        note=c.get("note"),
        evidence=c.get("evidence", []),
        status=WaterfallStatus(c["status"]),
        effective_status=WaterfallStatus(effective_status(c)),
        override=(
            OverrideOut(
                status=WaterfallStatus(override["status"]),
                reason=override["reason"],
                by=uuid.UUID(override["by"]),
                at=datetime.fromisoformat(override["at"]),
            )
            if override
            else None
        ),
    )


def option_from_row(row: WaterfallResult) -> WaterfallOptionOut:
    return WaterfallOptionOut(
        option=row.option,
        order_no=row.order_no,
        status=row.status,
        original_status=row.original_status,
        conditions=[_condition_result(c) for c in row.conditions],
        overridden=row.overridden,
        override_reason=row.override_reason,
        overridden_by=row.overridden_by,
        overridden_at=row.overridden_at,
    )


def recommendation_from_view(view: WaterfallView) -> LmRecommendationOut:
    rule_set = view.run.config_versions.get("rule_set")
    seeded = bool(view.report and view.report.report.source == ReportSource.SEEDED_SAMPLE)
    lender = view.lender_view
    ordered = [view.calculations[i] for i in (lender.calculation_ids if lender else [])]
    return LmRecommendationOut(
        run_id=view.run.id,
        run_status=view.run.status,
        source="seeded_sample" if seeded else "rules_engine",
        notice=SEEDED_NOTICE if seeded else None,
        rule_set=(
            RuleSetOut(
                name=rule_set["name"],
                version=rule_set["version"],
                label=rule_set["label"],
                banner=rule_set.get("banner")
                or (ILLUSTRATIVE_BANNER if rule_set["label"] == "illustrative" else None),
            )
            if rule_set
            else None
        ),
        waterfall=[option_from_row(o) for o in view.options],
        lender_view=(
            LenderViewOut(
                foreclosure_loss=exact(lender.foreclosure_loss) or "0.00",
                modification_cost=exact(lender.modification_cost) or "0.00",
                advantage=exact(lender.advantage) or "0.00",
                settings=lender.settings,
                figures=[
                    calc_from_row(c, f"rule_set@{rule_set['version']}" if rule_set else "")
                    for c in ordered
                ],
            )
            if lender
            else None
        ),
        report=report_from_view(view.report) if view.report else None,
    )

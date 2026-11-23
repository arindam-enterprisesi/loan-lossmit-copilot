"""Income analysis as the API sends it (Feature Design 2.7 and 2.8).

Amounts are strings (``"5980.00"``), so they stay exact: the client never turns them into floats
and never adds them up (the figures and their working are computed here, rule 1). Every figure
carries the document fields it came from, so the client can open the page and highlight the line.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.api.schemas.jobs import JobOut
from app.db.enums import AnalysisStatus, IncomeComponentKind
from app.db.models import Calculation, Flag, IncomeComponent
from app.services.analysis_config import AnalysisConfig
from app.services.income_runs import IncomeView

NOT_GENERATED = "explanations not generated"


def exact(value: Decimal | None) -> str | None:
    """A Decimal as plain text with no exponent: ``Decimal("5980.00")`` -> ``"5980.00"``."""
    return None if value is None else format(value, "f")


_PLACES = {
    "usd": Decimal("0.01"),
    "ratio": Decimal("0.000001"),
    "count": Decimal(1),
    "days": Decimal(1),
    "months": Decimal(1),
    "match": Decimal(1),
}


def shown(value: Decimal, unit: str) -> str:
    """A stored figure as text in the form its unit is read: cents, six places, or whole."""
    places = _PLACES.get(unit)
    return format(value.quantize(places) if places is not None else value.normalize(), "f")


class RefOut(BaseModel):
    """A figure's source: a stored field of one document, and the lines it was read from."""

    document_id: uuid.UUID
    field: str
    line_ids: list[str]


class CalcOut(BaseModel):
    id: uuid.UUID
    name: str
    value: str
    unit: str
    formula: str
    inputs: dict[str, str]
    working: str
    config_version: str
    evidence: list[RefOut]


class OverrideOut(BaseModel):
    """A person's include or exclude. The system's own decision stays in ``system_*``."""

    included: bool
    reason: str
    by: uuid.UUID
    at: datetime


class ComponentOut(BaseModel):
    id: uuid.UUID
    borrower: str
    employer: str | None
    component: IncomeComponentKind
    current_period: str | None
    ytd: str | None
    monthly: str
    included: bool
    exclusion_reason: str | None
    system_included: bool
    system_exclusion_reason: str | None
    override: OverrideOut | None
    calculation: CalcOut | None


class IncomeFlagOut(BaseModel):
    id: uuid.UUID
    code: str
    severity: str
    message: str
    status: str
    working: str | None
    refs: list[RefOut]


class IncomeAnalysisOut(BaseModel):
    id: uuid.UUID
    case_id: uuid.UUID
    status: AnalysisStatus
    started_at: datetime
    finished_at: datetime | None
    config_versions: dict[str, Any]
    candidate_monthly_income: str | None
    candidate_label: str
    candidate: CalcOut | None
    components: list[ComponentOut]
    flags: list[IncomeFlagOut]
    # Every other figure: periods elapsed, year-to-date checks, the annual history from W-2s and
    # returns, with its working.
    calculations: list[CalcOut]
    # The AI's possible explanations of the flags ("possible - to be confirmed") arrive with the
    # income explanation call. Until then there are none, and this says so.
    explanations: list[str] = Field(default_factory=list)
    explanations_note: str = NOT_GENERATED


class IncomeRunAccepted(BaseModel):
    job: JobOut
    analysis_id: uuid.UUID


class ComponentReviewIn(BaseModel):
    """Include or exclude a component. The reason is required either way (Feature Design 2.2)."""

    model_config = ConfigDict(extra="forbid")

    included: bool
    reason: str = Field(max_length=500)

    @field_validator("reason")
    @classmethod
    def _needs_a_reason(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("a reason is required")
        return value


# --- from rows ------------------------------------------------------------------------------


def calc_from_row(row: Calculation, version: str) -> CalcOut:
    return CalcOut(
        id=row.id,
        name=row.name,
        value=shown(row.value, row.unit),
        unit=row.unit,
        formula=row.formula,
        inputs={k: str(v) for k, v in (row.inputs or {}).items()},
        working=row.working,
        config_version=version,
        evidence=[RefOut(**e) for e in (row.evidence or [])],
    )


def component_from_row(
    row: IncomeComponent, calculations: dict[uuid.UUID, Calculation], version: str
) -> ComponentOut:
    calc = calculations.get(row.calculation_id) if row.calculation_id else None
    changed = row.updated_by is not None and row.updated_at is not None
    return ComponentOut(
        id=row.id,
        borrower=row.borrower,
        employer=row.employer,
        component=row.component,
        current_period=exact(row.current_period),
        ytd=exact(row.ytd),
        monthly=exact(row.monthly) or "0.00",
        included=row.included,
        exclusion_reason=row.exclusion_reason,
        system_included=row.original_included,
        system_exclusion_reason=row.original_exclusion_reason,
        override=(
            OverrideOut(
                included=row.included,
                reason=row.review_reason or "",
                by=row.updated_by,
                at=row.updated_at,
            )
            if changed
            else None
        ),
        calculation=calc_from_row(calc, version) if calc else None,
    )


def flag_from_income_row(row: Flag) -> IncomeFlagOut:
    evidence = row.evidence or {}
    return IncomeFlagOut(
        id=row.id,
        code=row.code,
        severity=row.severity.value,
        message=row.message,
        status=row.status.value,
        working=evidence.get("working"),
        refs=[RefOut(**r) for r in evidence.get("refs", [])],
    )


def analysis_from_view(view: IncomeView, cfg: AnalysisConfig) -> IncomeAnalysisOut:
    version = view.version_string()
    # Each component carries its own calculation; the rest are listed once, below.
    component_calcs = {c.calculation_id for c in view.components if c.calculation_id}
    return IncomeAnalysisOut(
        id=view.run.id,
        case_id=view.run.case_id,
        status=view.run.status,
        started_at=view.run.started_at,
        finished_at=view.run.finished_at,
        config_versions=view.run.config_versions,
        candidate_monthly_income=(
            shown(view.candidate.value, view.candidate.unit) if view.candidate else None
        ),
        candidate_label=cfg.income.candidate_label,
        candidate=calc_from_row(view.candidate, version) if view.candidate else None,
        components=[component_from_row(c, view.calculations, version) for c in view.components],
        flags=[flag_from_income_row(f) for f in view.flags],
        calculations=[
            calc_from_row(c, version)
            for c in view.ordered_calculations
            if c.id not in component_calcs and (view.candidate is None or c.id != view.candidate.id)
        ],
    )

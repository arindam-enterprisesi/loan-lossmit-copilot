"""Asset and liability analysis as the API sends it (Feature Design 3.7).

Amounts are strings (``"9226.32"``), so they stay exact: the client never turns them into floats and
never adds them up (rule 1). Every figure carries what it came from, so the client can open the page
and highlight the line (rule 2). The wording is for review: nothing here says a person is approved,
denied, offered or eligible (rule 3).
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.api.schemas.income import exact, shown
from app.api.schemas.jobs import JobOut
from app.db.enums import (
    AnalysisStatus,
    CategorySource,
    ObligationSource,
    TransactionCategory,
    TransactionDirection,
)
from app.db.models import Calculation, Flag, LoanScenario, Obligation, Transaction
from app.services.asset_runs import LARGE_DEPOSIT, PAYROLL_MATCH, AssetView

NOTE = "Candidate figures for the underwriter to review. They are not a decision."
HEADLINE = (
    "documented_assets",
    "funds_to_close",
    "funds_shortfall",
    "monthly_obligations",
    "front_end_ratio",
    "dti",
    "ltv",
)


class RefOut(BaseModel):
    """A figure's source: a line of a document, or the hand-entered loan scenario or income run."""

    document_id: uuid.UUID | None = None
    field: str | None = None
    line_ids: list[str] = Field(default_factory=list)
    source: str | None = None
    calculation: str | None = None


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


class ChangeOut(BaseModel):
    """A person's change to what the system decided. The system's own answer stays beside it."""

    reason: str
    by: uuid.UUID
    at: datetime


class TransactionOut(BaseModel):
    id: uuid.UUID
    document_id: uuid.UUID
    line_id: str
    account_last4: str | None
    posted_on: date
    description: str
    amount: str
    direction: TransactionDirection
    category: TransactionCategory
    category_source: CategorySource
    system_category: TransactionCategory
    counterparty: str | None
    needs_review: bool
    sourced: bool
    sourced_note: str | None
    change: ChangeOut | None
    payroll_match: CalcOut | None
    large_deposit: CalcOut | None


class ObligationOut(BaseModel):
    id: uuid.UUID
    creditor: str
    kind: str
    monthly_payment: str
    balance: str | None
    source: ObligationSource
    counts_toward_dti: bool
    reason: str
    system_counts_toward_dti: bool
    change: ChangeOut | None


class AssetFlagOut(BaseModel):
    id: uuid.UUID
    code: str
    severity: str
    message: str
    status: str
    working: str | None
    refs: list[RefOut]


class AssetAnalysisOut(BaseModel):
    id: uuid.UUID
    case_id: uuid.UUID
    status: AnalysisStatus
    started_at: datetime
    finished_at: datetime | None
    config_versions: dict[str, Any]
    note: str = NOTE
    documented_assets: CalcOut | None
    funds_to_close: CalcOut | None
    funds_shortfall: CalcOut | None
    monthly_obligations: CalcOut | None
    front_end_ratio: CalcOut | None
    dti: CalcOut | None
    ltv: CalcOut | None
    # The rest: DTI with each left-out income component counted, and so on.
    calculations: list[CalcOut]
    obligations: list[ObligationOut]
    transactions: list[TransactionOut]
    flags: list[AssetFlagOut]


class AssetRunAccepted(BaseModel):
    job: JobOut
    analysis_id: uuid.UUID


class LoanScenarioIn(BaseModel):
    """The sample loan, entered by hand. Nothing is priced (Feature Design 3.3)."""

    model_config = ConfigDict(extra="forbid")

    purpose: str = Field(min_length=1, max_length=64)
    occupancy: str = Field(min_length=1, max_length=64)
    property_value: Decimal = Field(gt=0, max_digits=12, decimal_places=2)
    loan_amount: Decimal = Field(ge=0, max_digits=12, decimal_places=2)
    proposed_housing_payment: Decimal = Field(ge=0, max_digits=12, decimal_places=2)
    funds_to_close: Decimal = Field(ge=0, max_digits=12, decimal_places=2)


class LoanScenarioOut(BaseModel):
    case_id: uuid.UUID
    purpose: str
    occupancy: str
    property_value: str
    loan_amount: str
    proposed_housing_payment: str
    funds_to_close: str
    updated_at: datetime | None


def _reason(value: str) -> str:
    value = value.strip()
    if not value:
        raise ValueError("a reason is required")
    return value


class TransactionReviewIn(BaseModel):
    """Give a line another category, or mark a deposit as sourced. The reason is required."""

    model_config = ConfigDict(extra="forbid")

    category: TransactionCategory | None = None
    sourced: bool | None = None
    reason: str = Field(max_length=500)

    _reason = field_validator("reason")(_reason)

    @model_validator(mode="after")
    def _one_change(self) -> TransactionReviewIn:
        if (self.category is None) == (self.sourced is None):
            raise ValueError("send either a category or sourced, not both and not neither")
        return self


class ObligationReviewIn(BaseModel):
    """Include a debt in the DTI or leave it out. The reason is required either way."""

    model_config = ConfigDict(extra="forbid")

    counts_toward_dti: bool
    reason: str = Field(max_length=500)

    _reason = field_validator("reason")(_reason)


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


def _change(row: Transaction | Obligation) -> ChangeOut | None:
    if row.updated_by is None or row.updated_at is None:
        return None
    return ChangeOut(reason=row.review_reason or "", by=row.updated_by, at=row.updated_at)


def transaction_from_row(row: Transaction, view: AssetView) -> TransactionOut:
    version = view.version_string()
    match = view.calc_for_line(PAYROLL_MATCH, row.document_id, row.line_ref)
    large = view.calc_for_line(LARGE_DEPOSIT, row.document_id, row.line_ref)
    return TransactionOut(
        id=row.id,
        document_id=row.document_id,
        line_id=row.line_ref,
        account_last4=row.account_last4,
        posted_on=row.posted_on,
        description=row.description,
        amount=exact(row.amount) or "0.00",
        direction=row.direction,
        category=row.category,
        category_source=row.category_source,
        system_category=row.original_category or row.category,
        counterparty=row.counterparty,
        needs_review=row.needs_review,
        sourced=row.sourced,
        sourced_note=row.sourced_note,
        change=_change(row),
        payroll_match=calc_from_row(match, version) if match else None,
        large_deposit=calc_from_row(large, version) if large else None,
    )


def obligation_from_row(row: Obligation) -> ObligationOut:
    return ObligationOut(
        id=row.id,
        creditor=row.creditor,
        kind=row.kind,
        monthly_payment=exact(row.monthly_payment) or "0.00",
        balance=exact(row.balance),
        source=row.source,
        counts_toward_dti=row.counts_toward_dti,
        reason=row.reason,
        system_counts_toward_dti=row.original_counts_toward_dti,
        change=_change(row),
    )


def flag_from_row(row: Flag) -> AssetFlagOut:
    evidence = row.evidence or {}
    return AssetFlagOut(
        id=row.id,
        code=row.code,
        severity=row.severity.value,
        message=row.message,
        status=row.status.value,
        working=evidence.get("working"),
        refs=[RefOut(**r) for r in evidence.get("refs", [])],
    )


def analysis_from_view(view: AssetView) -> AssetAnalysisOut:
    version = view.version_string()
    headline = {name: view.calc(name) for name in HEADLINE}
    per_line = {PAYROLL_MATCH, LARGE_DEPOSIT}
    return AssetAnalysisOut(
        id=view.run.id,
        case_id=view.run.case_id,
        status=view.run.status,
        started_at=view.run.started_at,
        finished_at=view.run.finished_at,
        config_versions=view.run.config_versions,
        **{n: calc_from_row(c, version) if c else None for n, c in headline.items()},
        calculations=[
            calc_from_row(c, version)
            for c in view.calculations
            if c.name not in HEADLINE and c.name not in per_line
        ],
        obligations=[obligation_from_row(o) for o in view.obligations],
        transactions=[transaction_from_row(t, view) for t in view.transactions],
        flags=[flag_from_row(f) for f in view.flags],
    )


def scenario_from_row(row: LoanScenario) -> LoanScenarioOut:
    return LoanScenarioOut(
        case_id=row.case_id,
        purpose=row.purpose,
        occupancy=row.occupancy,
        property_value=exact(row.property_value) or "0.00",
        loan_amount=exact(row.loan_amount) or "0.00",
        proposed_housing_payment=exact(row.proposed_housing_payment) or "0.00",
        funds_to_close=exact(row.funds_to_close) or "0.00",
        updated_at=row.updated_at,
    )

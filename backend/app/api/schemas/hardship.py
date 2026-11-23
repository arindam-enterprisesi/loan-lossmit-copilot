"""Hardship assessment response shapes (Feature Design 7.7).

The profile is what the borrower says. Each item carries the quote and the line IDs it came from
(rule 2) and ``verified``: whether code found the quote in those lines. Nothing here is a decision:
no field says anything is approved, denied, offered or eligible.

A specialist's confirmation of an item is sent beside it (``confirmation``), with the value as read,
the value confirmed, who, when and why, labelled "reviewer-confirmed". The reading itself is never
changed (rule 6). The budget is the two-basis budget of Feature Design 7.5: ``budget`` has one line
per category with the stated and observed amounts, ``measures`` the figures computed from them (each
with its working), ``checks`` the consistency checks with both values, and ``budget_flags`` what
code found worth a look. All of it is empty until the budget has been computed.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.api.schemas.assets import AssetFlagOut, CalcOut, ChangeOut, calc_from_row
from app.api.schemas.assets import flag_from_row as asset_flag_from_row
from app.api.schemas.documents import FlagOut, flag_from_row
from app.api.schemas.income import exact
from app.api.schemas.jobs import JobOut
from app.db.models import BudgetLine
from app.prompts.schemas.hardship import HardshipConfig
from app.services.budget import MEASURE_ORDER, slug
from app.services.budget_runs import BudgetView
from app.services.hardship_runs import HardshipView


class QuotedOut(BaseModel):
    """A short quote copied from the letter, where it is, and whether code found it there."""

    quote: str | None
    lines: list[str]
    verified: bool
    check_flags: list[str]


class ConfirmationOut(BaseModel):
    """A specialist's confirmation or correction of an item. The item itself is the reading."""

    status: Literal["confirmed", "corrected"]
    value: str
    original: str | None
    reason: str | None
    by: uuid.UUID
    at: datetime
    label: str


class ReasonOut(QuotedOut):
    category: str
    category_label: str
    sensitive: bool  # record only the category and its financial effect, never the details
    financial_effect: str
    confirmation: ConfirmationOut | None = None


class OnsetOut(QuotedOut):
    as_stated: str | None
    month: str | None  # "YYYY-MM" when the letter makes it clear
    confirmation: ConfirmationOut | None = None


class DurationOut(QuotedOut):
    category: Literal["temporary", "long_term", "unknown"]
    confirmation: ConfirmationOut | None = None


class IntentOut(QuotedOut):
    category: Literal["keep", "sell", "unsure"]
    confirmation: ConfirmationOut | None = None


class TimelineEventOut(QuotedOut):
    when: str | None
    event: str


class EnclosedDocumentOut(QuotedOut):
    document: str


class ProfileOut(BaseModel):
    primary_reason: ReasonOut
    other_reasons: list[ReasonOut]
    onset: OnsetOut
    duration: DurationOut
    intent: IntentOut
    timeline: list[TimelineEventOut]
    enclosed_documents: list[EnclosedDocumentOut]


class BudgetLineOut(BaseModel):
    id: uuid.UUID
    category: str
    stated: str | None
    # What the statements show: the latest statement month that has a debit in this line.
    observed: str | None
    observed_month: str | None
    # A person's one-off adjustment of the observed amount, and the amount that counts.
    adjusted: str | None
    adjustment_reason: str | None
    effective_observed: str | None
    # Stated against what counts, and whether the gap is above the tolerance.
    difference: str | None
    flagged: bool
    change: ChangeOut | None
    stated_calc: CalcOut | None
    observed_calc: CalcOut | None


class CheckOut(BaseModel):
    """A consistency check shown with both values (Feature Design 7.2 step 2)."""

    name: str
    agrees: bool
    working: str
    values: dict[str, str]


class HardshipRunAccepted(BaseModel):
    job: JobOut


class HardshipAssessmentOut(BaseModel):
    run_id: uuid.UUID
    source: Literal["model", "seeded_sample"]
    created_at: datetime
    # The letter the line IDs belong to; null when no letter is on the case yet.
    letter_document_id: uuid.UUID | None
    config_version: str
    config_label: Literal["illustrative", "authoritative"]
    profile: ProfileOut
    flags: list[FlagOut]
    confirmed_by: uuid.UUID | None = None
    confirmed_at: datetime | None = None
    budget: list[BudgetLineOut]
    measures: list[CalcOut]
    checks: list[CheckOut]
    budget_flags: list[AssetFlagOut]
    budget_note: str | None = None


def _reason(item: dict[str, Any], config: HardshipConfig) -> dict[str, Any]:
    category = next((c for c in config.categories if c.key == item["category"]), None)
    return {
        **item,
        "category_label": category.label if category else item["category"],
        "sensitive": category.sensitive if category else False,
    }


def assessment_from_view(
    view: HardshipView, config: HardshipConfig, budget: BudgetView | None = None
) -> HardshipAssessmentOut:
    row = view.profile
    versions = view.run.config_versions
    version = ", ".join(
        f"{kind}@{versions[kind]['version']}"
        for kind in ("hardship", "thresholds")
        if kind in versions
    )
    lines, measures, checks, budget_flags, note = _budget_parts(budget, version)
    return HardshipAssessmentOut(
        run_id=view.run.id,
        source=row.source.value,
        created_at=row.created_at,
        letter_document_id=row.document_id,
        config_version=view.run.config_versions["hardship"]["version"],
        config_label=view.run.config_versions["hardship"]["label"],
        profile=ProfileOut(
            primary_reason=ReasonOut.model_validate(_reason(row.primary_reason, config)),
            other_reasons=[ReasonOut.model_validate(_reason(r, config)) for r in row.reasons],
            onset=OnsetOut.model_validate(row.onset),
            duration=DurationOut.model_validate(row.duration),
            intent=IntentOut.model_validate(row.intent),
            timeline=[TimelineEventOut.model_validate(t) for t in row.timeline],
            enclosed_documents=[
                EnclosedDocumentOut.model_validate(d) for d in row.enclosed_documents
            ],
        ),
        flags=[flag_from_row(f) for f in view.flags],
        confirmed_by=row.confirmed_by,
        confirmed_at=row.confirmed_at,
        budget=lines,
        measures=measures,
        checks=checks,
        budget_flags=budget_flags,
        budget_note=note,
    )


# --- what a person sends ---------------------------------------------------------------------


class ItemIn(BaseModel):
    """Confirm an item as read (send ``{}``), or correct it (send the value and a reason)."""

    model_config = ConfigDict(extra="forbid")

    value: str | None = Field(default=None, max_length=64)
    reason: str | None = Field(default=None, max_length=500)

    @field_validator("value", "reason")
    @classmethod
    def _strip(cls, value: str | None) -> str | None:
        return value.strip() or None if value is not None else None


class ConfirmationsIn(BaseModel):
    """Confirm or correct the judgements the investor rules rely on. Name each item you mean."""

    model_config = ConfigDict(extra="forbid")

    primary_reason: ItemIn | None = None
    onset: ItemIn | None = None
    duration: ItemIn | None = None
    intent: ItemIn | None = None


class BudgetAdjustIn(BaseModel):
    """Count a different observed amount for a line (for example, part of it was one-off), with a
    reason. ``adjusted_amount: null`` clears an adjustment. The reason is required either way."""

    model_config = ConfigDict(extra="forbid")

    adjusted_amount: Decimal | None = Field(default=None, ge=0, max_digits=12, decimal_places=2)
    reason: str = Field(max_length=500)

    @field_validator("reason")
    @classmethod
    def _needs_a_reason(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("a reason is required")
        return value


# --- the budget, from rows -------------------------------------------------------------------


def _line(row: BudgetLine, view: BudgetView, version: str) -> BudgetLineOut:
    by_name = {c.name: c for c in view.calculations}
    stated_calc = by_name.get(f"stated_{slug(row.category)}")
    observed_calc = by_name.get(f"observed_{slug(row.category)}")
    effective = row.adjusted_amount if row.adjusted_amount is not None else row.observed_amount
    difference = (
        abs(row.stated_amount - effective)
        if row.stated_amount is not None and effective is not None
        else None
    )
    change = (
        ChangeOut(reason=row.adjustment_reason or "", by=row.updated_by, at=row.updated_at)
        if row.updated_by is not None and row.updated_at is not None
        else None
    )
    month = observed_calc.inputs.get("month") if observed_calc else None
    return BudgetLineOut(
        id=row.id,
        category=row.category,
        stated=exact(row.stated_amount),
        observed=exact(row.observed_amount),
        observed_month=str(month) if month else None,
        adjusted=exact(row.adjusted_amount),
        adjustment_reason=row.adjustment_reason,
        effective_observed=exact(effective),
        difference=exact(difference),
        flagged=row.flagged,
        change=change,
        stated_calc=calc_from_row(stated_calc, version) if stated_calc else None,
        observed_calc=calc_from_row(observed_calc, version) if observed_calc else None,
    )


def _budget_parts(
    budget: BudgetView | None, version: str
) -> tuple[list[BudgetLineOut], list[CalcOut], list[CheckOut], list[AssetFlagOut], str | None]:
    if budget is None or not budget.lines:
        return [], [], [], [], "The budget has not been computed for this reading yet."
    line_names = {
        f"{kind}_{slug(row.category)}" for row in budget.lines for kind in ("stated", "observed")
    }
    rank = {name: n for n, name in enumerate(MEASURE_ORDER)}
    ordered = sorted(budget.calculations, key=lambda c: (rank.get(c.name, len(rank)), c.name))
    measures = [c for c in ordered if c.name not in line_names and not c.name.startswith("check_")]
    checks = [
        CheckOut(
            name=c.name,
            agrees=c.value == 1,
            working=c.working,
            values={k: str(v) for k, v in (c.inputs or {}).items()},
        )
        for c in ordered
        if c.name.startswith("check_")
    ]
    return (
        [_line(row, budget, version) for row in budget.lines],
        [calc_from_row(c, version) for c in measures],
        checks,
        [asset_flag_from_row(f) for f in budget.flags],
        None,
    )

"""Hardship assessment response shapes (Feature Design 7.7).

The profile is what the borrower says. Each item carries the quote and the line IDs it came from
(rule 2) and ``verified``: whether code found the quote in those lines. Nothing here is a decision:
no field says anything is approved, denied, offered or eligible.

``budget`` and ``measures`` are reserved for the budget and its checks (D6): empty until then.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel

from app.api.schemas.documents import FlagOut, flag_from_row
from app.prompts.schemas.hardship import HardshipConfig
from app.services.hardship_runs import HardshipView


class QuotedOut(BaseModel):
    """A short quote copied from the letter, where it is, and whether code found it there."""

    quote: str | None
    lines: list[str]
    verified: bool
    check_flags: list[str]


class ReasonOut(QuotedOut):
    category: str
    category_label: str
    sensitive: bool  # record only the category and its financial effect, never the details
    financial_effect: str


class OnsetOut(QuotedOut):
    as_stated: str | None
    month: str | None  # "YYYY-MM" when the letter makes it clear


class DurationOut(QuotedOut):
    category: Literal["temporary", "long_term", "unknown"]


class IntentOut(QuotedOut):
    category: Literal["keep", "sell", "unsure"]


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
    budget: list[dict[str, Any]]
    measures: list[dict[str, Any]]


def _reason(item: dict[str, Any], config: HardshipConfig) -> dict[str, Any]:
    category = next((c for c in config.categories if c.key == item["category"]), None)
    return {
        **item,
        "category_label": category.label if category else item["category"],
        "sensitive": category.sensitive if category else False,
    }


def assessment_from_view(view: HardshipView, config: HardshipConfig) -> HardshipAssessmentOut:
    row = view.profile
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
        budget=[],
        measures=[],
    )

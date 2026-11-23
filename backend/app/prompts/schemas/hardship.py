"""Output model for hardship@1 (Feature Design 7.5) and its settings (backend/config/hardship.yaml).

The model reads the letter into a profile: reasons from the configured category
list (one primary), onset, duration, intent, a timeline and the documents the
borrower says are enclosed. Every item carries a short quote and the line IDs it
came from; ``app.llm.checks.verify_quotes`` checks each quote against those lines.

The category list is configuration, so the output model is built from it at run
time (``hardship_profile_model``): the reason ``category`` is an enum of the
configured keys, and a provider's schema mode cannot return anything else.
"""

from __future__ import annotations

import typing
from functools import cache
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, create_model, field_validator

from app.prompts.schemas.fields import Schema

DEFAULT_HARDSHIP_CONFIG_PATH = Path(__file__).resolve().parents[3] / "config" / "hardship.yaml"


# --- settings --------------------------------------------------------------------------------


class HardshipCategory(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    key: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    label: str
    # Medical, family and similar matters: record only the category and financial effect.
    sensitive: bool = False


class HardshipConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    version: str
    label: Literal["illustrative", "authoritative"]
    categories: tuple[HardshipCategory, ...] = Field(min_length=1)
    max_quote_chars: int = Field(gt=0)

    @field_validator("categories")
    @classmethod
    def _unique_with_other(
        cls, categories: tuple[HardshipCategory, ...]
    ) -> tuple[HardshipCategory, ...]:
        keys = [c.key for c in categories]
        if len(set(keys)) != len(keys):
            raise ValueError("category keys must be unique")
        if "other" not in keys:
            raise ValueError("the category list needs an 'other' entry")
        return categories

    @property
    def keys(self) -> tuple[str, ...]:
        return tuple(c.key for c in self.categories)


def load_hardship_config(path: Path | None = None) -> HardshipConfig:
    with (path or DEFAULT_HARDSHIP_CONFIG_PATH).open(encoding="utf-8") as fh:
        return HardshipConfig.model_validate(yaml.safe_load(fh))


# --- output ----------------------------------------------------------------------------------


class Quoted(Schema):
    """A short quote copied exactly from the letter, and the line IDs it is on.

    ``quote`` is null (and ``lines`` empty) only when the letter says nothing about it.
    """

    quote: str | None
    lines: list[str]


class Reason(Quoted):
    category: str  # narrowed to the configured keys by hardship_profile_model()
    financial_effect: str


class Onset(Quoted):
    as_stated: str | None
    month: str | None  # "YYYY-MM" when the letter makes the month and year clear


class Duration(Quoted):
    category: Literal["temporary", "long_term", "unknown"]


class Intent(Quoted):
    category: Literal["keep", "sell", "unsure"]


class TimelineEvent(Quoted):
    when: str | None
    event: str


class EnclosedDocument(Quoted):
    document: str


class HardshipProfile(Schema):
    primary_reason: Reason
    other_reasons: list[Reason]
    onset: Onset
    duration: Duration
    intent: Intent
    timeline: list[TimelineEvent]
    enclosed_documents: list[EnclosedDocument]


@cache
def hardship_profile_model(category_keys: tuple[str, ...]) -> type[HardshipProfile]:
    """The output model with ``category`` limited to the configured keys."""
    # Literal["reduction_in_income", ...], built from configuration.
    category: Any = typing.Literal.__getitem__(category_keys)
    reason: Any = create_model("HardshipReason", __base__=Reason, category=(category, ...))
    profile: type[HardshipProfile] = create_model(
        "HardshipProfileResult",
        __base__=HardshipProfile,
        primary_reason=(reason, ...),
        other_reasons=(list[reason], ...),
    )
    return profile

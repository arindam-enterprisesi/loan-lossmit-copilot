"""Settings for the analyses: ``income_method.yaml``, ``thresholds.yaml`` and ``checklists.yaml``.

Every setting carries its value, its label (illustrative or authoritative) and its source (CLAUDE.md
rule 4), and each file has a version. A loader validates them with Pydantic, and a run records which
version of each file it used (``config_versions``, with a hash of the file's bytes, because a
version label alone cannot prove a file was not edited). Nothing here is a model call or a
calculation: the numbers are read, and ``app.services.calculations`` does the arithmetic.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal
from functools import lru_cache
from pathlib import Path
from typing import Generic, Literal, TypeVar

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.db.enums import IncomeComponentKind, TransactionCategory
from app.services.document_config import FlagTemplate

CONFIG_DIR = Path(__file__).resolve().parents[2] / "config"
INCOME_METHOD_PATH = CONFIG_DIR / "income_method.yaml"
THRESHOLDS_PATH = CONFIG_DIR / "thresholds.yaml"
CHECKLISTS_PATH = CONFIG_DIR / "checklists.yaml"

Label = Literal["illustrative", "authoritative"]
T = TypeVar("T")


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Setting(_Strict, Generic[T]):
    """One setting: its value, its label and where it comes from."""

    value: T
    label: Label
    source: str = Field(min_length=1)


# --- income_method.yaml ---------------------------------------------------------------------


class ComponentSpec(_Strict):
    keywords: Setting[list[str]]


class FrequencySpec(_Strict):
    periods_per_year: int = Field(gt=0)
    min_days: int = Field(gt=0)
    max_days: int = Field(gt=0)
    aliases: list[str]

    @model_validator(mode="after")
    def _days_in_order(self) -> FrequencySpec:
        if self.min_days > self.max_days:
            raise ValueError("min_days is above max_days")
        return self


def _words(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", text.lower()))


class IncomeMethodConfig(_Strict):
    version: str
    label: Label
    source: str = Field(min_length=1)
    candidate_label: str
    components: dict[str, ComponentSpec]
    variable_history_months: Setting[int]
    pay_frequencies: Setting[dict[str, FrequencySpec]]
    employer_suffixes: Setting[list[str]]
    deferral_codes: Setting[list[str]]
    flags: dict[str, FlagTemplate]

    @model_validator(mode="after")
    def _known_components_and_templates(self) -> IncomeMethodConfig:
        allowed = {kind.value for kind in IncomeComponentKind}
        unknown = set(self.components) - allowed
        if unknown:
            raise ValueError(f"unknown income components: {sorted(unknown)}")
        if "cannot_check" not in self.flags:
            raise ValueError("flags must define cannot_check")
        return self

    def flag(self, code: str, **values: object) -> tuple[str, str]:
        """The severity and filled-in message for ``code`` (or ``code:variant``)."""
        template = self.flags[code]
        return template.severity, template.message.format(**values)

    def component_for(self, description: str | None) -> str | None:
        """Which component an earnings line belongs to, by the words in its description.

        Overtime, bonus and commission are looked for first, so "Regular overtime" is overtime.
        """
        if not description:
            return None
        words = _words(description)
        order = [c for c in self.components if c != "base"] + (
            ["base"] if "base" in self.components else []
        )
        for component in order:
            if words & {k.lower() for k in self.components[component].keywords.value}:
                return component
        return None

    def frequency_for(self, printed: str | None) -> tuple[str, FrequencySpec] | None:
        """The frequency a printed word names ("Biweekly" gives ``("biweekly", spec)``)."""
        if not printed:
            return None
        wanted = " ".join(printed.lower().replace("-", " ").split())
        for name, spec in self.pay_frequencies.value.items():
            aliases = {" ".join(a.lower().replace("-", " ").split()) for a in spec.aliases}
            if wanted in aliases:
                return name, spec
        return None


# --- thresholds.yaml ------------------------------------------------------------------------


class ThresholdsConfig(_Strict):
    version: str
    label: Label
    source: str = Field(min_length=1)
    # Income (Feature Design 2.3).
    tolerance_absolute: Setting[Decimal]
    tolerance_relative: Setting[Decimal]
    decline_threshold: Setting[Decimal]
    # Assets and liabilities (Feature Design 3.3).
    large_deposit_minimum: Setting[Decimal]
    recurring_debit_min_months: Setting[int]
    recurring_debit_tolerance: Setting[Decimal]
    payroll_match_tolerance: Setting[Decimal]
    payroll_match_days: Setting[int]
    dti_min_liability_payment: Setting[Decimal]
    dti_exclude_rent_on_purchase: Setting[bool]
    dti_review_level: Setting[Decimal]
    # The hardship budget (Feature Design 7.3 and 7.5).
    stated_vs_observed_share: Setting[Decimal]
    stated_vs_observed_amount: Setting[Decimal]
    pay_vs_hours_points: Setting[Decimal]
    budget_categories: Setting[list[str]]
    budget_category_map: Setting[dict[str, str]]
    # The credit report (Feature Design 4.3 and 4.5).
    credit_score_method: Setting[Literal["middle_of_three_lower_of_two"]]
    credit_late_lookback_months: Setting[int]
    credit_inquiry_window_days: Setting[int]
    credit_inquiry_match_days: Setting[int]
    credit_utilization_review_level: Setting[Decimal]
    # Flag messages for the asset, budget and credit checks: templates, filled in by code (rule 3).
    flags: dict[str, FlagTemplate]

    def flag(self, code: str, **values: object) -> tuple[str, str]:
        """The severity and filled-in message for ``code`` (or ``code:variant``)."""
        template = self.flags[code]
        return template.severity, template.message.format(**values)

    @model_validator(mode="after")
    def _sensible(self) -> ThresholdsConfig:
        if self.tolerance_absolute.value < 0 or self.tolerance_relative.value < 0:
            raise ValueError("a tolerance cannot be negative")
        if not Decimal(0) < self.decline_threshold.value < Decimal(1):
            raise ValueError("decline_threshold is a share between 0 and 1")
        for name in (
            "large_deposit_minimum",
            "recurring_debit_tolerance",
            "payroll_match_tolerance",
            "dti_min_liability_payment",
            "stated_vs_observed_amount",
            "pay_vs_hours_points",
        ):
            if getattr(self, name).value < 0:
                raise ValueError(f"{name} cannot be negative")
        if self.recurring_debit_min_months.value < 1:
            raise ValueError("recurring_debit_min_months counts statement months, at least 1")
        if self.payroll_match_days.value < 0:
            raise ValueError("payroll_match_days cannot be negative")
        if not Decimal(0) < self.dti_review_level.value < Decimal(1):
            raise ValueError("dti_review_level is a share between 0 and 1")
        if not Decimal(0) <= self.stated_vs_observed_share.value <= Decimal(1):
            raise ValueError("stated_vs_observed_share is a share between 0 and 1")
        if not Decimal(0) < self.credit_utilization_review_level.value <= Decimal(1):
            raise ValueError("credit_utilization_review_level is a share between 0 and 1")
        for name in (
            "credit_late_lookback_months",
            "credit_inquiry_window_days",
            "credit_inquiry_match_days",
        ):
            if getattr(self, name).value < 0:
                raise ValueError(f"{name} cannot be negative")
        lines = self.budget_categories.value
        if len(set(lines)) != len(lines):
            raise ValueError("budget_categories must be unique")
        known = {c.value for c in TransactionCategory}
        for category, line in self.budget_category_map.value.items():
            if category not in known:
                raise ValueError(f"budget_category_map: {category!r} is not a transaction category")
            if line not in lines:
                raise ValueError(f"budget_category_map: {line!r} is not a budget category")
        return self

    def tolerance_for(self, a: Decimal, b: Decimal) -> Decimal:
        """1.00 or 0.5% of the larger figure, whichever is larger (Feature Design 2.3)."""
        relative = self.tolerance_relative.value * max(abs(a), abs(b))
        return max(self.tolerance_absolute.value, relative)

    def stated_vs_observed_tolerance(self, stated: Decimal, observed: Decimal) -> Decimal:
        """10% of the larger figure or 25.00, whichever is larger (Feature Design 7.3).

        A stated and an observed amount that differ by more than this are flagged.
        """
        relative = self.stated_vs_observed_share.value * max(abs(stated), abs(observed))
        return max(self.stated_vs_observed_amount.value, relative)


# --- checklists.yaml ------------------------------------------------------------------------

Rule = Literal["coverage_days", "coverage_months", "tax_years", "recency", "present"]
_RULE_PARAMETER = {
    "coverage_days": "days",
    "coverage_months": "months",
    "tax_years": "year_offsets",
    "recency": "max_age_days",
}
REQUIRED_MESSAGES = (
    "missing",
    "coverage_days",
    "coverage_months",
    "tax_years",
    "recency",
    "present",
    "signed",
    "incomplete_document",
    "needs_review",
    "satisfied",
)


class ChecklistItem(_Strict):
    id: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    label: str
    noun: str
    doc_type: str
    rule: Rule
    days: Setting[int] | None = None
    months: Setting[int] | None = None
    year_offsets: Setting[list[int]] | None = None
    max_age_days: Setting[int] | None = None
    signed: bool = False

    @model_validator(mode="after")
    def _has_what_its_rule_needs(self) -> ChecklistItem:
        needed = _RULE_PARAMETER.get(self.rule)
        if needed and getattr(self, needed) is None:
            raise ValueError(f"item {self.id}: rule {self.rule} needs {needed}")
        return self


class Checklist(_Strict):
    title: str
    pillar: Literal["underwriting", "loss_mitigation"]
    employment_types: list[str]
    version: str
    label: Label
    source: str = Field(min_length=1)
    items: list[ChecklistItem] = Field(min_length=1)

    @model_validator(mode="after")
    def _unique_items(self) -> Checklist:
        ids = [item.id for item in self.items]
        if len(ids) != len(set(ids)):
            raise ValueError("two items share an id")
        return self


class ChecklistsConfig(_Strict):
    version: str
    label: Label
    source: str = Field(min_length=1)
    messages: dict[str, str]
    checklists: dict[str, Checklist]

    @model_validator(mode="after")
    def _messages_and_ids(self) -> ChecklistsConfig:
        missing = [key for key in REQUIRED_MESSAGES if key not in self.messages]
        if missing:
            raise ValueError(f"messages is missing {missing}")
        for checklist_id in self.checklists:
            if not re.fullmatch(r"[a-z0-9-]+@[0-9]+", checklist_id):
                raise ValueError(f"checklist id {checklist_id!r} is not name@version")
        return self

    def message(self, key: str, **values: object) -> str:
        return self.messages[key].format(**values)

    def get(self, checklist_id: str) -> Checklist | None:
        return self.checklists.get(checklist_id)


# --- what a run used ------------------------------------------------------------------------


@dataclass(frozen=True)
class ConfigUse:
    """One settings file as a run used it: recorded in ``config_versions`` and on the run."""

    kind: Literal["income_method", "thresholds", "checklist", "rule_set"]
    name: str
    version: str
    label: str
    source: str
    content_hash: str

    def as_json(self) -> dict[str, str]:
        return {
            "name": self.name,
            "version": self.version,
            "label": self.label,
            "hash": self.content_hash,
        }


@dataclass(frozen=True)
class AnalysisConfig:
    income: IncomeMethodConfig
    thresholds: ThresholdsConfig
    checklists: ChecklistsConfig
    hashes: Mapping[str, str]  # file kind -> SHA-256 of the file's bytes

    def uses(self, *, checklist_id: str | None = None) -> list[ConfigUse]:
        """The settings a run used: the income method and thresholds, or a checklist."""
        if checklist_id is not None:
            checklist = self.checklists.checklists[checklist_id]
            return [
                ConfigUse(
                    "checklist",
                    checklist_id,
                    self.checklists.version,
                    checklist.label,
                    checklist.source,
                    self.hashes["checklist"],
                )
            ]
        return [
            ConfigUse(
                "income_method",
                "income_method",
                self.income.version,
                self.income.label,
                self.income.source,
                self.hashes["income_method"],
            ),
            ConfigUse(
                "thresholds",
                "thresholds",
                self.thresholds.version,
                self.thresholds.label,
                self.thresholds.source,
                self.hashes["thresholds"],
            ),
        ]

    @staticmethod
    def snapshot(uses: list[ConfigUse]) -> dict[str, dict[str, str]]:
        """``analysis_runs.config_versions``: ``{kind: {name, version, label, hash}}``."""
        return {use.kind: use.as_json() for use in uses}

    def calc_version(self, *kinds: Literal["income_method", "thresholds"]) -> str:
        """``Calc.config_version``: ``"income_method@2026-11-19.1, thresholds@2026-11-19.1"``."""
        versions = {"income_method": self.income.version, "thresholds": self.thresholds.version}
        return ", ".join(f"{kind}@{versions[kind]}" for kind in kinds)


# --- loading --------------------------------------------------------------------------------


def _read(path: Path) -> tuple[object, str]:
    data = path.read_bytes()
    return yaml.safe_load(data), hashlib.sha256(data).hexdigest()


def load_analysis_config(
    income_path: Path | None = None,
    thresholds_path: Path | None = None,
    checklists_path: Path | None = None,
) -> AnalysisConfig:
    income, income_hash = _read(income_path or INCOME_METHOD_PATH)
    thresholds, thresholds_hash = _read(thresholds_path or THRESHOLDS_PATH)
    checklists, checklists_hash = _read(checklists_path or CHECKLISTS_PATH)
    return AnalysisConfig(
        income=IncomeMethodConfig.model_validate(income),
        thresholds=ThresholdsConfig.model_validate(thresholds),
        checklists=ChecklistsConfig.model_validate(checklists),
        hashes={
            "income_method": income_hash,
            "thresholds": thresholds_hash,
            "checklist": checklists_hash,
        },
    )


@lru_cache
def get_analysis_config() -> AnalysisConfig:
    return load_analysis_config()

"""The investor rule set, read from ``backend/config/rule_sets`` (Feature Design 8.3).

A rule set is versioned configuration kept with the code (rule 4): its options in waterfall order,
each option's conditions, the numbers they use, the lender view settings, and the passage of the
sample guide each condition cites. Every number carries a label (``illustrative`` or
``authoritative``) and a source. Numbers are quoted strings in the file so they stay exact.

The file says *what* is evaluated; ``rules_engine`` is the code that evaluates it. A condition names
one of a closed set of evaluators (``kind``), so a settings file can change a number or the order of
options, but it cannot run anything.
"""

from __future__ import annotations

import hashlib
from decimal import Decimal
from functools import lru_cache
from pathlib import Path
from typing import Literal

import yaml
from pydantic import Field, model_validator

from app.db.enums import WaterfallOption
from app.services.analysis_config import ConfigUse, Label, Setting, _Strict

RULE_SETS_DIR = Path(__file__).resolve().parents[2] / "config" / "rule_sets"
DEFAULT_RULE_SET = "sample_investor_a_v1"

ConditionKind = Literal[
    "hardship_resolved",
    "duration_is",
    "intent_is",
    "surplus_at_least_arrears_share",
    "surplus_at_least",
    "months_delinquent_at_most",
    "target_payment_below_contractual",
    "no_earlier_option_met",
    "none_defined",
]
WATERFALL_ORDER = list(WaterfallOption)


class ConditionSpec(_Strict):
    id: str = Field(min_length=1)
    kind: ConditionKind
    label: str = Field(min_length=1)
    expression: str = Field(min_length=1)
    passage_id: str = Field(min_length=1)
    # The key of the setting this condition uses, when it uses one.
    setting: str | None = None
    # The values a judgement must have (``duration_is``, ``intent_is``).
    allowed: list[str] = Field(default_factory=list)


class OptionSpec(_Strict):
    option: WaterfallOption
    conditions: list[ConditionSpec] = Field(min_length=1)


class RuleSettings(_Strict):
    surplus_basis: Setting[Literal["stated", "observed"]]
    repayment_plan_months: Setting[Decimal]
    deferral_minimum_surplus: Setting[Decimal]
    max_months_delinquent: Setting[Decimal]
    target_payment_pct: Setting[Decimal]


class LenderViewSettings(_Strict):
    property_value: Setting[Decimal]
    liquidation_discount_pct: Setting[Decimal]
    foreclosure_and_carrying_costs: Setting[Decimal]
    horizon_months: Setting[int]
    redefault_chance_pct: Setting[Decimal]


class RuleSetConfig(_Strict):
    version: str = Field(min_length=1)
    name: str = Field(min_length=1)
    label: Label
    source: str = Field(min_length=1)
    banner: str = Field(min_length=1)
    settings: RuleSettings
    lender_view: LenderViewSettings
    options: list[OptionSpec] = Field(min_length=1)

    @model_validator(mode="after")
    def _in_waterfall_order(self) -> RuleSetConfig:
        keys = [o.option for o in self.options]
        if keys != [k for k in WATERFALL_ORDER if k in keys] or len(set(keys)) != len(keys):
            raise ValueError("options must be listed once each, in waterfall order")
        ids = [c.id for o in self.options for c in o.conditions]
        if len(set(ids)) != len(ids):
            raise ValueError("condition ids must be unique")
        for option in self.options:
            for condition in option.conditions:
                if condition.setting and not hasattr(self.settings, condition.setting):
                    raise ValueError(f"{condition.id}: unknown setting {condition.setting!r}")
                needs_values = condition.kind in ("duration_is", "intent_is")
                if needs_values and not condition.allowed:
                    raise ValueError(f"{condition.id}: list the values that count as met")
        return self

    def setting_value(self, key: str) -> Decimal:
        value = getattr(self.settings, key).value
        assert isinstance(value, Decimal)
        return value


class LoadedRuleSet:
    """A rule set with the hash of its file, so a run can record exactly what it used."""

    def __init__(self, config: RuleSetConfig, content_hash: str) -> None:
        self.config = config
        self.content_hash = content_hash

    def use(self) -> ConfigUse:
        """How the run records it: kind ``rule_set``, named as people know it."""
        c = self.config
        return ConfigUse("rule_set", c.name, c.version, c.label, c.source, self.content_hash)

    def snapshot(self) -> dict[str, dict[str, str]]:
        """``analysis_runs.config_versions["rule_set"]``, with the banner the screen shows."""
        return {"rule_set": {**self.use().as_json(), "banner": self.config.banner}}


def load_rule_set(name: str = DEFAULT_RULE_SET, directory: Path | None = None) -> LoadedRuleSet:
    path = (directory or RULE_SETS_DIR) / f"{name}.yaml"
    data = path.read_bytes()
    config = RuleSetConfig.model_validate(yaml.safe_load(data))
    return LoadedRuleSet(config, hashlib.sha256(data).hexdigest())


@lru_cache
def get_rule_set() -> LoadedRuleSet:
    return load_rule_set()

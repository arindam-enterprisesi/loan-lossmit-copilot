"""The rule set file: loaded, validated, versioned and labelled (rule 4)."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
import yaml
from pydantic import ValidationError

from app.db.enums import ConfigKind, WaterfallOption
from app.services.rules_config import (
    DEFAULT_RULE_SET,
    RULE_SETS_DIR,
    RuleSetConfig,
    get_rule_set,
    load_rule_set,
)

RAW: dict[str, Any] = yaml.safe_load(
    (RULE_SETS_DIR / f"{DEFAULT_RULE_SET}.yaml").read_text("utf-8")
)


def build(**changes: Any) -> RuleSetConfig:
    return RuleSetConfig.model_validate({**RAW, **changes})


def test_the_sample_rule_set_is_versioned_and_labelled_illustrative() -> None:
    loaded = get_rule_set()
    config = loaded.config
    assert (config.name, config.version, config.label) == ("Sample Investor A", "1", "illustrative")
    assert config.banner == "Illustrative: not an actual investor's requirements."
    assert len(loaded.content_hash) == 64


def test_every_setting_is_labelled_and_has_a_source() -> None:
    config = get_rule_set().config
    for group in (config.settings, config.lender_view):
        for name in group.model_fields_set:
            setting = getattr(group, name)
            assert setting.label in ("illustrative", "authoritative"), name
            assert setting.source, name


def test_numbers_are_exact_decimals_never_floats() -> None:
    config = get_rule_set().config
    assert config.setting_value("target_payment_pct") == Decimal("35")
    assert config.lender_view.property_value.value == Decimal("265000.00")
    assert config.lender_view.horizon_months.value == 36
    assert not any(
        isinstance(setting.value, float)
        for group in (config.settings, config.lender_view)
        for setting in (getattr(group, n) for n in group.model_fields_set)
    )


def test_options_are_in_waterfall_order_and_every_option_is_there() -> None:
    config = get_rule_set().config
    assert [o.option for o in config.options] == list(WaterfallOption)


def test_it_is_recorded_as_a_rule_set_under_the_name_people_know_it_by() -> None:
    use = get_rule_set().use()
    assert (use.kind, use.name, use.version, use.label) == (
        "rule_set",
        "Sample Investor A",
        "1",
        "illustrative",
    )
    assert ConfigKind(use.kind) is ConfigKind.RULE_SET
    snapshot = get_rule_set().snapshot()["rule_set"]
    assert snapshot["hash"] == get_rule_set().content_hash and snapshot["banner"]


def test_options_out_of_order_are_refused() -> None:
    options = list(reversed(RAW["options"]))
    with pytest.raises(ValidationError, match="waterfall order"):
        build(options=options)


def test_a_condition_naming_a_setting_that_does_not_exist_is_refused() -> None:
    options = yaml.safe_load(yaml.safe_dump(RAW["options"]))
    options[0]["conditions"][1]["setting"] = "made_up"
    with pytest.raises(ValidationError, match="unknown setting"):
        build(options=options)


def test_duplicate_condition_ids_are_refused() -> None:
    options = yaml.safe_load(yaml.safe_dump(RAW["options"]))
    options[1]["conditions"][0]["id"] = options[0]["conditions"][0]["id"]
    with pytest.raises(ValidationError, match="unique"):
        build(options=options)


def test_a_judgement_condition_must_list_what_counts_as_met() -> None:
    options = yaml.safe_load(yaml.safe_dump(RAW["options"]))
    options[1]["conditions"][0]["allowed"] = []
    with pytest.raises(ValidationError, match="values that count as met"):
        build(options=options)


def test_a_setting_without_a_label_is_refused() -> None:
    settings = yaml.safe_load(yaml.safe_dump(RAW["settings"]))
    del settings["target_payment_pct"]["label"]
    with pytest.raises(ValidationError):
        build(settings=settings)


def test_an_unknown_kind_of_condition_cannot_be_run() -> None:
    options = yaml.safe_load(yaml.safe_dump(RAW["options"]))
    options[0]["conditions"][0]["kind"] = "run_this_code"
    with pytest.raises(ValidationError):
        build(options=options)


def test_a_changed_file_changes_the_hash(tmp_path: Path) -> None:
    text = (RULE_SETS_DIR / f"{DEFAULT_RULE_SET}.yaml").read_text("utf-8")
    (tmp_path / "other.yaml").write_text(text.replace('value: "35"', 'value: "30"'), "utf-8")
    other = load_rule_set("other", tmp_path)
    assert other.content_hash != get_rule_set().content_hash
    assert other.config.setting_value("target_payment_pct") == Decimal("30")

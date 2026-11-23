"""The income method, thresholds and checklists: shipped values, validation, versions, templates."""

from __future__ import annotations

import re
import string
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
import yaml
from pydantic import ValidationError

from app.services.analysis_config import (
    CHECKLISTS_PATH,
    INCOME_METHOD_PATH,
    THRESHOLDS_PATH,
    AnalysisConfig,
    Setting,
    get_analysis_config,
    load_analysis_config,
)

CFG = get_analysis_config()
# The Feature Design's own label says "qualifying income"; "qualifies" and the rest are never used.
BLOCKED = re.compile(
    r"\b(approve[sd]?|approving|approval|deny|denies|denied|offer(s|ed)?|eligible|eligibility|"
    r"qualifies|qualified)\b",
    re.IGNORECASE,
)


def _edited(tmp_path: Path, source: Path, change: Any) -> Path:
    data = yaml.safe_load(source.read_text(encoding="utf-8"))
    change(data)
    path = tmp_path / source.name
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    return path


# --- the shipped settings -------------------------------------------------------------------


def test_every_file_is_versioned_labelled_and_sourced() -> None:
    for part in (CFG.income, CFG.thresholds, CFG.checklists):
        assert part.version and part.label in {"illustrative", "authoritative"} and part.source
    assert (CFG.income.version, CFG.thresholds.version, CFG.checklists.version) == (
        "2026-11-19.1",
        "2026-11-24.1",  # the assets and budget settings were added on D6
        "2026-11-19.1",
    )


def _settings(node: object) -> list[Setting[Any]]:
    found: list[Setting[Any]] = []
    if isinstance(node, Setting):
        found.append(node)
    elif isinstance(node, dict):
        for child in node.values():
            found += _settings(child)
    elif isinstance(node, list):
        for child in node:
            found += _settings(child)
    elif hasattr(type(node), "model_fields"):
        for name in type(node).model_fields:
            found += _settings(getattr(node, name))
    return found


def test_every_single_setting_carries_a_label_and_a_source() -> None:
    settings = _settings(CFG.income) + _settings(CFG.thresholds) + _settings(CFG.checklists)
    # 8 in the income method, 15 thresholds (3 for income, 12 for assets and the budget), 7
    # checklist parameters.
    assert len(settings) == 31
    assert {s.label for s in settings} == {"illustrative"}  # nothing is claimed authoritative
    assert all(s.source.strip() for s in settings)


def test_the_feature_designs_sample_values() -> None:
    assert CFG.income.variable_history_months.value == 24
    assert CFG.income.deferral_codes.value == ["D"]
    assert CFG.thresholds.tolerance_absolute.value == Decimal("1.00")
    assert CFG.thresholds.tolerance_relative.value == Decimal("0.005")
    assert CFG.thresholds.decline_threshold.value == Decimal("0.05")
    periods = {n: f.periods_per_year for n, f in CFG.income.pay_frequencies.value.items()}
    assert periods == {"weekly": 52, "biweekly": 26, "semi_monthly": 24, "monthly": 12}


def test_money_and_ratios_are_decimals_not_floats() -> None:
    for setting in (
        CFG.thresholds.tolerance_absolute,
        CFG.thresholds.tolerance_relative,
        CFG.thresholds.decline_threshold,
    ):
        assert isinstance(setting.value, Decimal)


def test_the_sample_checklists_follow_the_feature_design() -> None:
    wage = CFG.checklists.get("pillar1-wage-earner@1")
    assert wage is not None and wage.pillar == "underwriting"
    rules = {i.id: (i.doc_type, i.rule) for i in wage.items}
    assert rules == {
        "pay_stubs_30_days": ("pay_stub", "coverage_days"),
        "w2_two_years": ("w2", "tax_years"),
        "tax_returns_two_years": ("tax_return_1040", "tax_years"),
        "bank_statements_2_months": ("bank_statement", "coverage_months"),
        "credit_report_120_days": ("credit_report", "recency"),
    }
    by_id = {i.id: i for i in wage.items}
    assert by_id["pay_stubs_30_days"].days is not None
    assert by_id["pay_stubs_30_days"].days.value == 30
    assert by_id["w2_two_years"].year_offsets is not None
    assert by_id["w2_two_years"].year_offsets.value == [1, 2]
    assert by_id["bank_statements_2_months"].months is not None
    assert by_id["bank_statements_2_months"].months.value == 2
    assert by_id["credit_report_120_days"].max_age_days is not None
    assert by_id["credit_report_120_days"].max_age_days.value == 120

    hardship = CFG.checklists.get("pillar2-hardship@1")
    assert hardship is not None and hardship.pillar == "loss_mitigation"
    assert [i.id for i in hardship.items] == [
        "signed_application",
        "hardship_letter",
        "pay_stubs_30_days",
        "bank_statements_2_months",
    ]
    assert CFG.checklists.get("nope@1") is None


# --- reading the method ---------------------------------------------------------------------


@pytest.mark.parametrize(
    ("description", "component"),
    [
        ("Regular", "base"),
        ("Hourly wages", "base"),
        ("Overtime 1.5x", "overtime"),
        ("OT", "overtime"),
        ("Regular overtime", "overtime"),  # the more specific word wins
        ("Bonus", "bonus"),
        ("Sales commission", "commission"),
        ("Per diem", None),
        ("", None),
        (None, None),
    ],
)
def test_an_earnings_line_belongs_to_a_component_by_its_words(
    description: str | None, component: str | None
) -> None:
    assert CFG.income.component_for(description) == component


@pytest.mark.parametrize(
    ("printed", "name", "periods"),
    [
        ("Biweekly", "biweekly", 26),
        ("Bi-weekly", "biweekly", 26),
        ("BIWEEKLY", "biweekly", 26),
        ("Every two weeks", "biweekly", 26),
        ("Weekly", "weekly", 52),
        ("Semi-monthly", "semi_monthly", 24),
        ("Monthly", "monthly", 12),
    ],
)
def test_a_printed_pay_frequency_names_its_periods_per_year(
    printed: str, name: str, periods: int
) -> None:
    found = CFG.income.frequency_for(printed)
    assert found is not None and (found[0], found[1].periods_per_year) == (name, periods)


def test_an_unknown_frequency_is_not_guessed() -> None:
    assert CFG.income.frequency_for("Fortnightly-ish") is None
    assert CFG.income.frequency_for(None) is None and CFG.income.frequency_for("") is None


@pytest.mark.parametrize(
    ("a", "b", "tolerance"),
    [
        ("100.00", "100.00", "1.00"),  # 0.5% is 0.50, so the absolute 1.00 is larger
        ("200.00", "200.00", "1.00"),  # 0.5% is exactly 1.00
        ("1000.00", "1000.00", "5.00"),  # 0.5% is the larger
        ("74298.60", "74290.00", "371.4930"),  # of the larger figure
        ("-1000.00", "10.00", "5.00"),  # signs do not matter
    ],
)
def test_the_cross_document_tolerance_is_one_or_half_a_percent_whichever_is_larger(
    a: str, b: str, tolerance: str
) -> None:
    assert CFG.thresholds.tolerance_for(Decimal(a), Decimal(b)) == Decimal(tolerance)


# --- the assets and budget settings (Feature Design 3.3 and 7.3) -----------------------------


def test_the_assets_settings_are_the_feature_designs_sample_values() -> None:
    t = CFG.thresholds
    assert t.large_deposit_minimum.value == Decimal("1000.00")
    assert (t.recurring_debit_min_months.value, t.recurring_debit_tolerance.value) == (
        2,
        Decimal("1.00"),
    )
    assert (t.payroll_match_tolerance.value, t.payroll_match_days.value) == (Decimal("1.00"), 3)
    assert t.dti_review_level.value == Decimal("0.43")
    # "Include credit report liabilities with a payment above zero; exclude current rent on a
    # purchase of a primary residence."
    assert t.dti_min_liability_payment.value == Decimal("0.00")
    assert t.dti_exclude_rent_on_purchase.value is True


def test_the_budget_checks_have_their_flag_templates_and_a_labelled_pay_against_hours_limit() -> (
    None
):
    t = CFG.thresholds

    assert (
        t.pay_vs_hours_points.value == Decimal("5")
        and t.pay_vs_hours_points.label == "illustrative"
    )
    severity, message = t.flag("HB-W102", pay_change="-25.00%", hours_change="-25.00%")
    assert severity == "warning"
    assert (
        message
        == "Pay on the stubs changed by -25.00%, but the letter says hours changed by -25.00%."
    )
    assert t.flag("HB-I101", what="the budget", missing="the application")[0] == "info"
    for code in ("HB-W101", "HB-W103", "HB-W104", "HB-W105"):
        assert code in t.flags and t.flags[code].severity == "warning"


def test_the_stated_against_observed_tolerance_is_ten_percent_or_25_whichever_is_larger() -> None:
    t = CFG.thresholds
    assert (t.stated_vs_observed_share.value, t.stated_vs_observed_amount.value) == (
        Decimal("0.10"),
        Decimal("25.00"),
    )
    # The tolerance is 10% of the larger figure or 25.00, whichever is larger.
    assert t.stated_vs_observed_tolerance(Decimal("200.00"), Decimal("410.00")) == Decimal("41.00")
    assert t.stated_vs_observed_tolerance(Decimal("3420.00"), Decimal("3630.00")) == Decimal(
        "363.00"
    )
    assert t.stated_vs_observed_tolerance(Decimal("100.00"), Decimal("110.00")) == Decimal("25.00")


def test_the_budget_categories_and_the_map_from_transaction_categories() -> None:
    t = CFG.thresholds
    assert t.budget_categories.value == [
        "Housing (mortgage)",
        "Utilities",
        "Food and everyday",
        "Loan payments",
        "Other",
    ]
    mapping = t.budget_category_map.value
    assert mapping["housing payment"] == "Housing (mortgage)"
    assert mapping["utility"] == "Utilities"
    assert mapping["everyday spending"] == "Food and everyday"
    assert mapping["loan payment"] == mapping["credit card payment"] == "Loan payments"
    assert mapping["other"] == "Other"
    # Money moving between accounts is not an expense.
    assert "transfer out" not in mapping and "transfer in" not in mapping


def test_the_assets_settings_are_decimals_not_floats() -> None:
    t = CFG.thresholds
    for setting in (
        t.large_deposit_minimum,
        t.recurring_debit_tolerance,
        t.payroll_match_tolerance,
        t.dti_review_level,
        t.dti_min_liability_payment,
        t.stated_vs_observed_share,
        t.stated_vs_observed_amount,
    ):
        assert isinstance(setting.value, Decimal)


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("large_deposit_minimum", "-1.00"),
        ("recurring_debit_min_months", 0),
        ("recurring_debit_tolerance", "-0.01"),
        ("payroll_match_days", -1),
        ("dti_review_level", "1.50"),
        ("dti_review_level", "0"),
        ("stated_vs_observed_share", "1.5"),
        ("stated_vs_observed_amount", "-5"),
        ("pay_vs_hours_points", "-1"),
    ],
)
def test_a_nonsensical_assets_setting_is_rejected(tmp_path: Path, name: str, value: Any) -> None:
    def tweak(data: dict[str, Any]) -> None:
        data[name]["value"] = value

    with pytest.raises(ValidationError):
        load_analysis_config(thresholds_path=_edited(tmp_path, THRESHOLDS_PATH, tweak))


def test_the_budget_map_must_use_real_transaction_categories_and_known_budget_lines(
    tmp_path: Path,
) -> None:
    def unknown_key(data: dict[str, Any]) -> None:
        data["budget_category_map"]["value"]["gift"] = "Other"

    def unknown_line(data: dict[str, Any]) -> None:
        data["budget_category_map"]["value"]["utility"] = "Hobbies"

    for tweak in (unknown_key, unknown_line):
        with pytest.raises(ValidationError):
            load_analysis_config(thresholds_path=_edited(tmp_path, THRESHOLDS_PATH, tweak))


# --- versions and hashes --------------------------------------------------------------------


def test_a_run_records_each_file_it_used_with_a_hash_of_its_bytes() -> None:
    uses = CFG.uses()
    assert [(u.kind, u.name, u.version, u.label) for u in uses] == [
        ("income_method", "income_method", "2026-11-19.1", "illustrative"),
        ("thresholds", "thresholds", "2026-11-24.1", "illustrative"),
    ]
    assert all(re.fullmatch(r"[0-9a-f]{64}", u.content_hash) for u in uses)
    snapshot = AnalysisConfig.snapshot(uses)
    assert set(snapshot) == {"income_method", "thresholds"}
    assert set(snapshot["income_method"]) == {"name", "version", "label", "hash"}

    [checklist] = CFG.uses(checklist_id="pillar1-wage-earner@1")
    assert (checklist.kind, checklist.name, checklist.label) == (
        "checklist",
        "pillar1-wage-earner@1",
        "illustrative",
    )


def test_editing_a_file_changes_its_hash_even_when_the_version_is_not_bumped(
    tmp_path: Path,
) -> None:
    def tweak(data: dict[str, Any]) -> None:
        data["variable_history_months"]["value"] = 12

    edited = load_analysis_config(income_path=_edited(tmp_path, INCOME_METHOD_PATH, tweak))
    assert edited.income.version == CFG.income.version
    assert edited.hashes["income_method"] != CFG.hashes["income_method"]
    assert edited.hashes["thresholds"] == CFG.hashes["thresholds"]
    assert edited.income.variable_history_months.value == 12


def test_calc_version_names_the_files_a_figure_used() -> None:
    assert CFG.calc_version("income_method", "thresholds") == (
        "income_method@2026-11-19.1, thresholds@2026-11-24.1"
    )


# --- validation -----------------------------------------------------------------------------


def _rejects(tmp_path: Path, source: Path, change: Any) -> None:
    kwargs = {
        INCOME_METHOD_PATH: "income_path",
        THRESHOLDS_PATH: "thresholds_path",
        CHECKLISTS_PATH: "checklists_path",
    }
    with pytest.raises(ValidationError):
        load_analysis_config(**{kwargs[source]: _edited(tmp_path, source, change)})


def test_a_label_must_be_illustrative_or_authoritative(tmp_path: Path) -> None:
    def tweak(data: dict[str, Any]) -> None:
        data["variable_history_months"]["label"] = "sample"

    _rejects(tmp_path, INCOME_METHOD_PATH, tweak)


def test_a_setting_without_a_source_is_rejected(tmp_path: Path) -> None:
    def drop(data: dict[str, Any]) -> None:
        del data["tolerance_absolute"]["source"]

    def blank(data: dict[str, Any]) -> None:
        data["tolerance_absolute"]["source"] = ""

    _rejects(tmp_path, THRESHOLDS_PATH, drop)
    _rejects(tmp_path, THRESHOLDS_PATH, blank)


def test_an_unknown_key_is_rejected_so_a_typo_cannot_hide(tmp_path: Path) -> None:
    def typo(data: dict[str, Any]) -> None:
        data["decline_treshold"] = data.pop("decline_threshold")

    _rejects(tmp_path, THRESHOLDS_PATH, typo)


def test_the_decline_threshold_is_a_share(tmp_path: Path) -> None:
    def too_big(data: dict[str, Any]) -> None:
        data["decline_threshold"]["value"] = "5"

    _rejects(tmp_path, THRESHOLDS_PATH, too_big)


def test_a_tolerance_cannot_be_negative(tmp_path: Path) -> None:
    def negative(data: dict[str, Any]) -> None:
        data["tolerance_absolute"]["value"] = "-1.00"

    _rejects(tmp_path, THRESHOLDS_PATH, negative)


def test_an_income_component_must_be_a_known_kind(tmp_path: Path) -> None:
    def add(data: dict[str, Any]) -> None:
        data["components"]["tips"] = data["components"]["bonus"]

    _rejects(tmp_path, INCOME_METHOD_PATH, add)


def test_a_pay_frequency_cannot_have_its_days_backwards(tmp_path: Path) -> None:
    def backwards(data: dict[str, Any]) -> None:
        data["pay_frequencies"]["value"]["weekly"].update(min_days=9, max_days=7)

    _rejects(tmp_path, INCOME_METHOD_PATH, backwards)


def test_the_cannot_check_template_is_required(tmp_path: Path) -> None:
    def drop(data: dict[str, Any]) -> None:
        del data["flags"]["cannot_check"]

    _rejects(tmp_path, INCOME_METHOD_PATH, drop)


def test_a_checklist_item_needs_the_setting_its_rule_reads(tmp_path: Path) -> None:
    def drop(data: dict[str, Any]) -> None:
        del data["checklists"]["pillar1-wage-earner@1"]["items"][0]["days"]

    _rejects(tmp_path, CHECKLISTS_PATH, drop)


def test_two_checklist_items_cannot_share_an_id(tmp_path: Path) -> None:
    def duplicate(data: dict[str, Any]) -> None:
        items = data["checklists"]["pillar1-wage-earner@1"]["items"]
        items.append(dict(items[0]))

    _rejects(tmp_path, CHECKLISTS_PATH, duplicate)


def test_a_checklist_id_is_name_at_version(tmp_path: Path) -> None:
    def rename(data: dict[str, Any]) -> None:
        data["checklists"]["wage-earner"] = data["checklists"].pop("pillar1-wage-earner@1")

    _rejects(tmp_path, CHECKLISTS_PATH, rename)


def test_every_gap_message_is_required(tmp_path: Path) -> None:
    def drop(data: dict[str, Any]) -> None:
        del data["messages"]["coverage_days"]

    _rejects(tmp_path, CHECKLISTS_PATH, drop)


# --- messages -------------------------------------------------------------------------------


def test_the_gap_message_reads_like_the_feature_designs_example() -> None:
    assert (
        CFG.checklists.message("coverage_days", found=14, required=30, noun="pay stubs")
        == "14 of 30 days of pay stubs found"
    )
    assert (
        CFG.checklists.message("tax_years", noun="W-2s", found="2025", missing="2024")
        == "W-2s found for 2025; missing 2024"
    )


def _template_fields(text: str) -> set[str]:
    return {name for _, name, _, _ in string.Formatter().parse(text) if name}


def test_no_message_or_label_uses_a_decision_word() -> None:
    texts = [CFG.income.candidate_label, *CFG.checklists.messages.values()]
    texts += [f.message for f in CFG.income.flags.values()]
    for checklist in CFG.checklists.checklists.values():
        texts += [checklist.title, *(i.label for i in checklist.items)]
    for text in texts:
        assert not BLOCKED.search(text), text


def test_the_candidate_label_is_the_feature_designs() -> None:
    assert CFG.income.candidate_label == (
        "candidate — qualifying income is determined by the underwriter"
    )


def test_income_flag_templates_fill_and_have_the_expected_severities() -> None:
    values = {
        "tax_wages": "69,840.68",
        "year": "2025",
        "box1": "69,840.68",
        "difference": "0.00",
        "tolerance": "1.00",
        "stub_employer": "A",
        "w2_employer": "B",
        "gap": "4,457.92",
        "codes": "D",
        "deferrals": "4,457.92",
        "label": "Medicare wages",
        "drop": "6%",
        "from_label": "2025",
        "from_amount": "74,298.60",
        "to_label": "the 2026 pace",
        "to_amount": "70,000.00",
        "threshold": "5%",
        "direction": "rose",
        "change": "5.49%",
        "component": "Overtime",
        "history": "9 months",
        "required": "24",
        "average": "444.41",
        "current": "204.93",
        "printed": "Weekly",
        "days": "14",
        "rule": "the trend",
        "missing": "the 2024 W-2",
        "description": "Per diem",
        "by_date": "19",
        "by_ytd": "18.00",
    }
    for code, template in CFG.income.flags.items():
        assert _template_fields(template.message) <= set(values), code
        severity, message = CFG.income.flag(code, **values)
        assert severity == template.severity and message and "{" not in message, code
    assert CFG.income.flags["INC-CHK-03:explained"].severity == "info"
    assert CFG.income.flags["INC-CHK-04:trend"].severity == "info"
    assert CFG.income.flags["cannot_check"].severity == "info"
    assert CFG.income.flags["INC-CHK-04"].severity == "warning"

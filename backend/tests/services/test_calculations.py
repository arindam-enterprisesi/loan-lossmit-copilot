"""The calculations beyond the worked examples: rounding, tolerance edges, bad inputs, no floats."""

from __future__ import annotations

import ast
import inspect
from datetime import date
from decimal import Decimal as D

import pytest

from app.services import calculations
from app.services.analysis_config import get_analysis_config
from app.services.calculations import (
    Calc,
    Check,
    annualized_pace,
    base_pay_hourly,
    candidate_total,
    deferral_gap,
    employer_match,
    months_between,
    pay_frequency_check,
    pay_from_current,
    percent,
    periods_elapsed,
    periods_from_ytd,
    wages_vs_w2_box1,
    yoy_trend,
    ytd_monthly_average,
)

CFG = get_analysis_config()
V = CFG.calc_version("income_method", "thresholds")
SUFFIXES = CFG.income.employer_suffixes.value


# --- Decimal only ---------------------------------------------------------------------------


def test_the_module_never_uses_a_float() -> None:
    tree = ast.parse(inspect.getsource(calculations))
    names = {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)}
    assert "float" not in names
    constants = {n.value for n in ast.walk(tree) if isinstance(n, ast.Constant)}
    assert not any(isinstance(c, float) for c in constants)


def test_every_figure_is_a_decimal_and_every_input_a_string() -> None:
    calcs = [
        base_pay_hourly(D("34.50"), D("80"), 26, version=V),
        pay_from_current("salary_monthly", D("2500.00"), 24, version=V),
        ytd_monthly_average("o", D("3897.10"), 19, 26, version=V),
        annualized_pace("p", D("58339.50"), 19, 26, version=V),
        candidate_total([("Base pay", D("5980.00"))], version=V),
    ]
    for calc in calcs:
        assert isinstance(calc, Calc) and isinstance(calc.value, D)
        assert calc.formula and calc.working and calc.config_version == V
        assert all(isinstance(v, str) for v in calc.inputs.values())


# --- rounding -------------------------------------------------------------------------------


def test_money_rounds_half_up_at_the_last_step_only() -> None:
    # 0.01 x 5 x 26 / 12 = 0.108333...: the cent is decided once, at the end.
    assert base_pay_hourly(D("0.01"), D("5"), 26, version=V).value == D("0.11")
    # 1.00 x 1.5 x 1 / 12 = 0.125 exactly: half up gives 0.13, not banker's 0.12.
    assert base_pay_hourly(D("1.00"), D("1.5"), 1, version=V).value == D("0.13")
    # 100.00 x 3 / (7 x 12) = 3.5714...: no early rounding of the quotient.
    assert ytd_monthly_average("x", D("100.00"), 7, 3, version=V).value == D("3.57")


def test_percent_is_two_decimals_half_up() -> None:
    assert percent(D("0.054901")) == "5.49%"
    assert percent(D("0.07445")) == "7.45%"  # 7.445 half up
    assert percent(D("0")) == "0.00%"


def test_a_salary_line_without_hours_uses_its_current_amount() -> None:
    calc = pay_from_current("salary_monthly", D("2500.00"), 24, version=V)
    assert calc.value == D("5000.00")
    assert calc.working == "2,500.00 x 24 / 12 = 5,000.00"


# --- inputs the formulas cannot take --------------------------------------------------------


@pytest.mark.parametrize(
    "call",
    [
        lambda: base_pay_hourly(D("0"), D("80"), 26, version=V),
        lambda: base_pay_hourly(D("34.50"), D("-1"), 26, version=V),
        lambda: base_pay_hourly(D("34.50"), D("80"), 0, version=V),
        lambda: ytd_monthly_average("x", D("1"), 0, 26, version=V),
        lambda: annualized_pace("x", D("1"), 0, 26, version=V),
        lambda: yoy_trend("W", "a", D("0"), "b", D("1"), D("0.05"), version=V),
    ],
)
def test_a_zero_or_negative_divisor_is_refused_not_guessed(call: object) -> None:
    with pytest.raises(ValueError):
        call()  # type: ignore[operator]


# --- tolerance edges ------------------------------------------------------------------------


def test_the_wages_comparison_passes_at_the_tolerance_and_fails_a_cent_over() -> None:
    tol = D("1.00")
    at = wages_vs_w2_box1(D("69840.68"), D("69841.68"), tol, version=V)
    over = wages_vs_w2_box1(D("69840.68"), D("69841.69"), tol, version=V)
    assert at.passed and not over.passed
    assert over.details["difference"] == "1.01"
    assert over.calc.value == D("1.01")


def test_the_deferral_gap_is_explained_only_within_the_tolerance() -> None:
    explained = deferral_gap(D("1000.00"), D("900.00"), D("100.50"), ["D"], D("1.00"), version=V)
    unexplained = deferral_gap(D("1000.00"), D("900.00"), D("102.00"), ["D"], D("1.00"), version=V)
    assert explained.passed and not unexplained.passed


def test_no_gap_and_no_deferrals_is_explained_and_says_none() -> None:
    check = deferral_gap(D("50000.00"), D("50000.00"), D("0"), [], D("1.00"), version=V)
    assert check.passed and check.calc.value == D("0.00") and check.details["codes"] == "none"


def test_a_gap_with_no_deferral_code_is_not_explained() -> None:
    check = deferral_gap(D("50000.00"), D("46000.00"), D("0"), [], D("1.00"), version=V)
    assert not check.passed and check.details["gap"] == "4,000.00"


# --- employer names -------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("a", "b"),
    [
        ("Cedar Valley Manufacturing, Inc.", "Cedar Valley Manufacturing"),
        ("CEDAR VALLEY MANUFACTURING INC", "cedar valley manufacturing, inc."),
        ("Smith & Sons Co.", "Smith and Sons"),
        ("Acme, LLC", "ACME"),
    ],
)
def test_the_same_employer_written_differently_matches(a: str, b: str) -> None:
    assert employer_match(a, b, SUFFIXES, version=V).passed


@pytest.mark.parametrize(
    ("a", "b"),
    [
        ("Cedar Valley Manufacturing, Inc.", "Cedar Ridge Manufacturing, Inc."),
        ("Cedar Valley", "Cedar Valley Foods"),
        ("Inc.", "Inc."),  # nothing but a suffix is not a name
        ("", "Acme"),
    ],
)
def test_different_or_empty_employers_do_not_match(a: str, b: str) -> None:
    check = employer_match(a, b, SUFFIXES, version=V)
    assert not check.passed and check.calc.value == D(0)


# --- trends ---------------------------------------------------------------------------------


def test_a_fall_is_reported_as_a_fall_with_its_size() -> None:
    check = yoy_trend("Wages", "2025", D("74298.60"), "2026", D("70000.00"), D("0.05"), version=V)
    assert not check.passed
    assert (check.details["direction"], check.details["drop"]) == ("fell", "5.79%")
    assert check.calc.working == "(70,000.00 - 74,298.60) / 74,298.60 = -5.79%"


def test_no_change_is_a_rise_of_zero() -> None:
    check = yoy_trend("Wages", "a", D("100.00"), "b", D("100.00"), D("0.05"), version=V)
    assert (
        check.passed and check.details["direction"] == "rose" and check.details["change"] == "0.00%"
    )


# --- pay frequency --------------------------------------------------------------------------


def test_semi_monthly_pay_accepts_the_period_lengths_a_month_can_give() -> None:
    found = CFG.income.frequency_for("Semi-monthly")
    assert found is not None
    spec = found[1]
    for start, end in (
        (date(2026, 9, 1), date(2026, 9, 15)),  # 15 days
        (date(2026, 9, 16), date(2026, 9, 30)),  # 15 days
        (date(2026, 10, 16), date(2026, 10, 31)),  # 16 days
        (date(2026, 2, 16), date(2026, 2, 28)),  # 13 days
    ):
        assert pay_frequency_check("Semi-monthly", spec, start, end, version=V).passed
    assert not pay_frequency_check(
        "Semi-monthly", spec, date(2026, 9, 1), date(2026, 9, 7), version=V
    ).passed


# --- pay periods ----------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("day", "per_year", "expected"),
    [
        (date(2026, 1, 1), 26, 1),  # never below the first period
        (date(2026, 1, 5), 26, 1),
        (date(2026, 10, 2), 26, 19),
        (date(2026, 12, 31), 26, 26),
        (date(2026, 10, 2), 52, 39),
        (date(2026, 10, 2), 24, 18),
        (date(2026, 10, 2), 12, 9),
    ],
)
def test_pay_periods_elapsed(day: date, per_year: int, expected: int) -> None:
    assert periods_elapsed(day, per_year) == expected


def test_the_cross_check_from_year_to_date_pay() -> None:
    assert periods_from_ytd(D("52440.00"), D("2760.00")) == D("19.00")
    assert periods_from_ytd(D("52440.00"), D("0")) is None
    assert periods_from_ytd(D("100.00"), D("30.00")) == D("3.33")  # not a whole number: a flag


@pytest.mark.parametrize(
    ("start", "end", "months"),
    [
        (date(2026, 1, 1), date(2026, 10, 2), 9),
        (date(2026, 1, 1), date(2026, 10, 1), 9),
        (date(2026, 1, 31), date(2026, 3, 1), 1),  # March 1 is before the 31st: not 2 months yet
        (date(2026, 1, 15), date(2026, 1, 15), 0),
        (date(2026, 5, 1), date(2026, 1, 1), 0),  # backwards never goes negative
        (date(2024, 1, 1), date(2026, 1, 1), 24),
    ],
)
def test_months_between(start: date, end: date, months: int) -> None:
    assert months_between(start, end) == months


# --- the candidate --------------------------------------------------------------------------


def test_the_candidate_with_nothing_included_is_zero_and_says_so() -> None:
    calc = candidate_total([], version=V)
    assert calc.value == D("0.00") and calc.working == "No component is included = 0.00"


def test_a_check_carries_its_calc_and_the_figures_a_flag_needs() -> None:
    check = wages_vs_w2_box1(D("100.00"), D("250.00"), D("1.00"), version=V)
    assert isinstance(check, Check) and isinstance(check.calc, Calc)
    assert check.details == {
        "tax_wages": "100.00",
        "box1": "250.00",
        "difference": "150.00",
        "tolerance": "1.00",
    }

"""Income, to the cent: the Feature Design's worked examples (sections 2.3, 2.5 and 2.8).

These figures are the ground truth. Daniel Reyes: base pay 5,980.00 a month, overtime 444.41 and
bonus 228.34 excluded because their history covers 2026 only, 6,424.41 with overtime, W-2 Box 5 up
5.49% from 2024 to 2025 and a 2026 pace of 79,833.00. The PRD sample is 28.00 x 80 x 26 / 12 =
4,853.33.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal as D

from app.services.analysis_config import get_analysis_config
from app.services.calculations import (
    annualized_pace,
    base_pay_hourly,
    candidate_total,
    deferral_gap,
    employer_match,
    months_between,
    pay_frequency_check,
    periods_elapsed,
    periods_from_ytd,
    variable_history_check,
    wages_vs_w2_box1,
    yoy_trend,
    ytd_monthly_average,
    ytd_per_period,
    ytd_vs_current,
)

CFG = get_analysis_config()
VERSION = CFG.calc_version("income_method", "thresholds")
THRESHOLDS = CFG.thresholds
BIWEEKLY = 26


def tolerance(a: str, b: str) -> D:
    return THRESHOLDS.tolerance_for(D(a), D(b))


# --- monthly figures ------------------------------------------------------------------------


def test_the_prd_sample_is_4853_33() -> None:
    calc = base_pay_hourly(D("28.00"), D("80.00"), 26, version=VERSION)
    assert calc.value == D("4853.33")
    assert calc.working == "28.00 x 80.00 x 26 / 12 = 4,853.33"
    assert calc.formula == "rate x regular hours x periods per year / 12"
    assert calc.inputs == {"rate": "28.00", "hours": "80.00", "periods_per_year": "26"}


def test_daniels_base_pay_is_5980_00_a_month() -> None:
    calc = base_pay_hourly(D("34.50"), D("80.00"), BIWEEKLY, version=VERSION)
    assert calc.value == D("5980.00")
    assert (calc.name, calc.unit) == ("base_pay_monthly", "usd")
    assert calc.working == "34.50 x 80.00 x 26 / 12 = 5,980.00"
    assert calc.config_version == "income_method@2026-11-19.1, thresholds@2026-11-24.2"


def test_daniels_overtime_and_bonus_year_to_date_averages() -> None:
    overtime = ytd_monthly_average("overtime_monthly", D("3897.10"), 19, BIWEEKLY, version=VERSION)
    bonus = ytd_monthly_average("bonus_monthly", D("2002.40"), 19, BIWEEKLY, version=VERSION)
    assert overtime.value == D("444.41")
    assert bonus.value == D("228.34")
    assert overtime.working == "3,897.10 x 26 / (19 x 12) = 444.41"
    assert bonus.working == "2,002.40 x 26 / (19 x 12) = 228.34"


def test_the_candidate_without_overtime_and_with_overtime() -> None:
    base = base_pay_hourly(D("34.50"), D("80.00"), BIWEEKLY, version=VERSION).value
    overtime = ytd_monthly_average("o", D("3897.10"), 19, BIWEEKLY, version=VERSION).value
    bonus = ytd_monthly_average("b", D("2002.40"), 19, BIWEEKLY, version=VERSION).value

    # Overtime and bonus are excluded: their history covers 2026 only.
    assert candidate_total([("Base pay", base)], version=VERSION).value == D("5980.00")
    # "Including overtime would make the candidate total 6,424.41" (Feature Design 2.8).
    with_overtime = candidate_total([("Base pay", base), ("Overtime", overtime)], version=VERSION)
    assert with_overtime.value == D("6424.41")
    assert with_overtime.working == "5,980.00 + 444.41 = 6,424.41 (Base pay, Overtime)"
    everything = candidate_total(
        [("Base pay", base), ("Overtime", overtime), ("Bonus", bonus)], version=VERSION
    )
    assert everything.value == D("6652.75")


def test_the_2026_pace_is_79833_00() -> None:
    pace = annualized_pace("gross_pay_pace", D("58339.50"), 19, BIWEEKLY, version=VERSION)
    assert pace.value == D("79833.00")
    assert pace.working == "58,339.50 x 26 / 19 = 79,833.00"


def test_the_pay_stub_is_in_pay_period_19() -> None:
    assert periods_elapsed(date(2026, 10, 2), BIWEEKLY) == 19  # the pay date
    assert periods_elapsed(date(2026, 9, 27), BIWEEKLY) == 19  # the period end agrees
    assert periods_from_ytd(D("52440.00"), D("2760.00")) == D("19.00")  # regular YTD / regular
    assert periods_from_ytd(D("58339.50"), D("3070.50")) == D("19.00")  # and gross agrees


# --- trends ---------------------------------------------------------------------------------


def test_w2_box_5_rose_5_49_percent_from_2024_to_2025() -> None:
    check = yoy_trend(
        "Medicare wages",
        "2024",
        D("70431.80"),
        "2025",
        D("74298.60"),
        THRESHOLDS.decline_threshold.value,
        version=VERSION,
    )
    assert check.calc.value == D("0.054901")
    assert check.calc.working == "(74,298.60 - 70,431.80) / 70,431.80 = 5.49%"
    assert check.passed  # a rise is not a decline
    assert (check.details["direction"], check.details["change"]) == ("rose", "5.49%")


def test_the_2026_pace_is_7_45_percent_above_2025() -> None:
    check = yoy_trend(
        "Medicare wages",
        "2025",
        D("74298.60"),
        "the 2026 pace",
        D("79833.00"),
        THRESHOLDS.decline_threshold.value,
        version=VERSION,
    )
    assert check.calc.value == D("0.074489")
    assert (check.details["direction"], check.details["change"]) == ("rose", "7.45%")


def test_a_drop_above_five_percent_is_a_decline_and_exactly_five_is_not() -> None:
    threshold = THRESHOLDS.decline_threshold.value

    def check(to: str) -> tuple[bool, str]:
        result = yoy_trend(
            "Wages", "2025", D("100000.00"), "2026", D(to), threshold, version=VERSION
        )
        return result.passed, result.details["drop"]

    assert check("95000.00") == (True, "5.00%")  # "above 5%" means more than 5%
    assert check("94999.00") == (False, "5.00%")  # 5.001%, shown to two decimals
    assert check("90000.00") == (False, "10.00%")


# --- cross-document checks ------------------------------------------------------------------


def test_the_1040_wages_equal_w2_box_1() -> None:
    check = wages_vs_w2_box1(
        D("69840.68"), D("69840.68"), tolerance("69840.68", "69840.68"), version=VERSION
    )
    assert check.passed and check.calc.value == D("0.00")
    assert check.details["difference"] == "0.00"


def test_box_5_minus_box_1_is_the_box_12_deferral_in_both_years() -> None:
    for box5, box1, deferral in (
        ("74298.60", "69840.68", "4457.92"),  # 2025
        ("70431.80", "66205.89", "4225.91"),  # 2024
    ):
        check = deferral_gap(
            D(box5), D(box1), D(deferral), ["D"], tolerance(deferral, deferral), version=VERSION
        )
        assert check.passed and check.calc.value == D(deferral)
    two025 = deferral_gap(
        D("74298.60"), D("69840.68"), D("4457.92"), ["D"], D("1.00"), version=VERSION
    )
    assert two025.details == {"gap": "4,457.92", "deferrals": "4,457.92", "codes": "D"}
    assert two025.calc.working == (
        "74,298.60 - 69,840.68 = 4,457.92; deferrals 4,457.92 (tolerance 1.00)"
    )


def test_the_employer_is_the_same_on_the_stub_and_the_w2() -> None:
    suffixes = CFG.income.employer_suffixes.value
    same = employer_match(
        "Cedar Valley Manufacturing, Inc.",
        "Cedar Valley Manufacturing, Inc.",
        suffixes,
        version=VERSION,
    )
    assert same.passed and same.calc.value == D(1)


def test_a_weekly_label_on_a_fourteen_day_period_does_not_fit_and_biweekly_does() -> None:
    start, end = date(2026, 9, 14), date(2026, 9, 27)
    found = CFG.income.frequency_for("Biweekly")
    weekly = CFG.income.frequency_for("Weekly")
    assert found is not None and weekly is not None
    fits = pay_frequency_check("Biweekly", found[1], start, end, version=VERSION)
    assert fits.passed and fits.calc.value == D(14)
    assert fits.calc.working == ("2026-09-27 - 2026-09-14 + 1 = 14 days; Biweekly pay is 14 days")
    wrong = pay_frequency_check("Weekly", weekly[1], start, end, version=VERSION)
    assert not wrong.passed and wrong.details == {"printed": "Weekly", "days": "14"}


def test_the_history_of_overtime_covers_9_months_and_24_are_needed() -> None:
    months = months_between(date(2026, 1, 1), date(2026, 10, 2))
    assert months == 9
    check = variable_history_check(
        "overtime", months, CFG.income.variable_history_months.value, version=VERSION
    )
    assert not check.passed
    assert check.details == {"history": "9 months", "required": "24"}


def test_year_to_date_pay_per_period_agrees_with_the_current_period() -> None:
    # Gross: 58,339.50 / 19 = 3,070.50, exactly this period's gross.
    gross_average = ytd_per_period("gross_ytd_per_period", D("58339.50"), 19, version=VERSION)
    assert gross_average.value == D("3070.50")
    gross = ytd_vs_current(
        "Gross pay",
        gross_average.value,
        D("3070.50"),
        tolerance("3070.50", "3070.50"),
        version=VERSION,
    )
    assert gross.passed
    # Overtime: 205.11 against 204.93 is 0.18 apart, inside the tolerance of 1.00 or 0.5%.
    overtime_average = ytd_per_period("o", D("3897.10"), 19, version=VERSION).value
    assert overtime_average == D("205.11")
    assert ytd_vs_current(
        "Overtime", overtime_average, D("204.93"), tolerance("205.11", "204.93"), version=VERSION
    ).passed

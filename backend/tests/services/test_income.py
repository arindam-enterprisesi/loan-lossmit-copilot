"""Income analysis over a case's documents: Daniel Reyes's figures from the Feature Design (2.8).

The documents are built as the real reader stores them (``earnings_001_hours`` and so on, from
``LlmExtractor``), with Daniel's values: base pay 5,980.00 a month, overtime 444.41 and bonus 228.34
excluded because their history covers 2026 only, W-2 Box 5 explained by the Box 12 deferral, and
a 2026 pace of 79,833.00 (7.45% above 2025).
"""

from __future__ import annotations

import re
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal as D

import pytest

from app.services.analysis_config import get_analysis_config
from app.services.case_facts import DocFacts, FieldFact
from app.services.document_config import get_document_fields
from app.services.income import FlagResult, IncomeOutcome, analyze
from app.services.normalize import normalize, stored_text

CFG = get_analysis_config()
FIELDS = get_document_fields()
BASE_TIME = datetime(2026, 10, 12, tzinfo=UTC)
BLOCKED = re.compile(r"\b(approve[sd]?|deny|denied|offer(s|ed)?|eligible|qualifies)\b", re.I)


def make(
    doc_type: str,
    values: dict[str, str],
    *,
    minutes: int = 0,
    status: str = "needs_review",
    flags: tuple[str, ...] = (),
) -> DocFacts:
    fields: dict[str, FieldFact] = {}
    for name, value in values.items():
        kind = FIELDS.kind_of(doc_type, name)
        fields[name] = FieldFact(
            name,
            value,
            normalize(kind, stored_text(kind, value)),
            (f"p1-L{len(fields) + 1}",),
            "unreviewed",
            "high",
        )
    return DocFacts(
        uuid.uuid4(),
        f"{doc_type}.pdf",
        doc_type,
        status,
        None,
        None,
        None,
        BASE_TIME + timedelta(minutes=minutes),
        fields,
        frozenset(flags),
    )


STUB = {
    "employer_name": "Cedar Valley Manufacturing, Inc.",
    "employee_name": "Daniel Reyes",
    "pay_frequency": "Biweekly",
    "pay_period_start": "2026-09-14",
    "pay_period_end": "2026-09-27",
    "pay_date": "2026-10-02",
    "earnings_001_description": "Regular",
    "earnings_001_hours": "80.00",
    "earnings_001_rate": "34.50",
    "earnings_001_current": "2,760.00",
    "earnings_001_ytd": "52,440.00",
    "earnings_002_description": "Overtime 1.5x",
    "earnings_002_hours": "3.96",
    "earnings_002_rate": "51.75",
    "earnings_002_current": "204.93",
    "earnings_002_ytd": "3,897.10",
    "earnings_003_description": "Bonus",
    "earnings_003_current": "105.57",
    "earnings_003_ytd": "2,002.40",
    "gross_pay_current": "3,070.50",
    "gross_pay_ytd": "58,339.50",
}
W2_2025 = {
    "tax_year": "2025",
    "employer_name": "Cedar Valley Manufacturing, Inc.",
    "employee_name": "Daniel Reyes",
    "box1_wages": "69,840.68",
    "box5_medicare_wages": "74,298.60",
    "box12_001_code": "D",
    "box12_001_amount": "4,457.92",
}
W2_2024 = {
    **W2_2025,
    "tax_year": "2024",
    "box1_wages": "66,205.89",
    "box5_medicare_wages": "70,431.80",
    "box12_001_amount": "4,225.91",
}
RETURN_2025 = {
    "tax_year": "2025",
    "taxpayer_names": "Daniel Reyes",
    "wages": "69,840.68",
    "total_income": "69,881.85",
}


def daniel(*extra: DocFacts, stub: dict[str, str] | None = None) -> list[DocFacts]:
    return [
        make("pay_stub", stub or STUB),
        make("w2", W2_2025, minutes=1),
        make("tax_return_1040", RETURN_2025, minutes=2),
        *extra,
    ]


def by_code(outcome: IncomeOutcome) -> dict[str, list[FlagResult]]:
    found: dict[str, list[FlagResult]] = {}
    for flag in outcome.flags:
        found.setdefault(flag.code, []).append(flag)
    return found


def codes(outcome: IncomeOutcome) -> list[str]:
    return sorted(f"{f.code}|{f.key}" for f in outcome.flags)


# --- Daniel Reyes ---------------------------------------------------------------------------


def test_daniels_components_and_candidate() -> None:
    outcome = analyze(daniel(), CFG)

    parts = {c.kind: c for c in outcome.components}
    assert list(parts) == ["base", "overtime", "bonus"]
    assert parts["base"].monthly == D("5980.00") and parts["base"].included
    assert parts["overtime"].monthly == D("444.41") and not parts["overtime"].included
    assert parts["bonus"].monthly == D("228.34") and not parts["bonus"].included
    assert (parts["base"].current_period, parts["base"].ytd) == (D("2760.00"), D("52440.00"))
    assert (parts["overtime"].current_period, parts["overtime"].ytd) == (D("204.93"), D("3897.10"))
    assert (parts["bonus"].current_period, parts["bonus"].ytd) == (D("105.57"), D("2002.40"))
    assert (parts["base"].borrower, parts["base"].employer) == (
        "Daniel Reyes",
        "Cedar Valley Manufacturing, Inc.",
    )

    assert outcome.candidate.value == D("5980.00")  # overtime and bonus are not counted
    assert outcome.candidate.working == "5,980.00 = 5,980.00 (Base pay)"
    assert outcome.candidate.name == "candidate_monthly_income"
    assert outcome.calcs[-1] is outcome.candidate


def test_overtime_and_bonus_are_excluded_with_the_reason_the_feature_design_gives() -> None:
    outcome = analyze(daniel(), CFG)
    parts = {c.kind: c for c in outcome.components}
    assert parts["overtime"].exclusion_reason == (
        "Overtime is excluded: its documented history is 9 months (2026 only), "
        "and 24 months are needed."
    )
    assert parts["bonus"].exclusion_reason == (
        "Bonus is excluded: its documented history is 9 months (2026 only), "
        "and 24 months are needed."
    )
    assert parts["base"].exclusion_reason is None


def test_each_component_has_its_working_and_the_fields_it_came_from() -> None:
    outcome = analyze(daniel(), CFG)
    parts = {c.kind: c for c in outcome.components}
    assert parts["base"].calc.working == "34.50 x 80.00 x 26 / 12 = 5,980.00"
    assert parts["overtime"].calc.working == "3,897.10 x 26 / (19 x 12) = 444.41"
    assert parts["bonus"].calc.working == "2,002.40 x 26 / (19 x 12) = 228.34"
    for part in parts.values():
        assert part.calc.config_version == "income_method@2026-11-19.1, thresholds@2026-11-24.2"
        assert part.calc.evidence and all(
            {"document_id", "field", "line_ids"} <= set(e) for e in part.calc.evidence
        )
    base_fields = {e["field"] for e in parts["base"].calc.evidence}
    assert {"earnings_001_hours", "earnings_001_rate"} <= base_fields


def test_the_flags_on_daniels_documents() -> None:
    outcome = analyze(daniel(), CFG)
    assert codes(outcome) == [
        "INC-CHK-03|deferrals-2025",  # Box 5 minus Box 1, explained by Box 12 code D
        "INC-CHK-04|trend-current",  # the 2026 pace against 2025
        "INC-W101|history-bonus",
        "INC-W101|history-overtime",
    ]
    flags = {f.key: f for f in outcome.flags}
    deferral = flags["deferrals-2025"]
    assert deferral.severity == "info"
    assert deferral.message == (
        "W-2 Box 5 is 4,457.92 above Box 1 for 2025, which the Box 12 deferral codes (D) "
        "account for."
    )
    assert deferral.working == (
        "74,298.60 - 69,840.68 = 4,457.92; deferrals 4,457.92 (tolerance 22.29)"
    )
    trend = flags["trend-current"]
    assert trend.severity == "info"
    assert trend.message == (
        "Medicare wages rose 7.45% from 2025 (74,298.60) to the 2026 pace (79,833.00)."
    )
    assert flags["history-overtime"].severity == "warning"


def test_every_check_that_passes_says_nothing_and_every_figure_is_still_kept() -> None:
    outcome = analyze(daniel(), CFG)
    names = {c.name for c in outcome.calcs}
    # Wages, employer, frequency and year to date all pass: no flag, but the working is kept.
    assert {
        "wages_vs_w2_box1_difference",
        "employer_match",
        "pay_period_days",
        "gross_pay_ytd_per_period",
        "gross_pay_ytd_vs_current",
        "periods_elapsed",
        "gross_pay_pace_2026",
        "box5_minus_box1",
    } <= names
    pace = next(c for c in outcome.calcs if c.name == "gross_pay_pace_2026")
    assert pace.value == D("79833.00")
    elapsed = next(c for c in outcome.calcs if c.name == "periods_elapsed")
    assert elapsed.value == D(19)


def test_the_annual_history_is_kept_with_where_it_was_read() -> None:
    outcome = analyze(daniel(make("w2", W2_2024, minutes=3)), CFG)
    history = {c.name: c.value for c in outcome.calcs if c.formula == "as printed on the document"}
    assert history == {
        "w2_box1_2024": D("66205.89"),
        "w2_box5_2024": D("70431.80"),
        "w2_box1_2025": D("69840.68"),
        "w2_box5_2025": D("74298.60"),
        "wages_1040_2025": D("69840.68"),
    }


def test_with_the_2024_w2_the_trend_from_2024_to_2025_is_5_49_percent() -> None:
    outcome = analyze(daniel(make("w2", W2_2024, minutes=3)), CFG)
    flags = {f.key: f for f in outcome.flags}
    assert flags["trend-w2"].message == (
        "Medicare wages rose 5.49% from 2024 (70,431.80) to 2025 (74,298.60)."
    )
    assert flags["deferrals-2024"].severity == "info"  # 4,225.91 is Box 12 code D that year too


def test_the_same_documents_always_give_the_same_analysis() -> None:
    docs = daniel(make("w2", W2_2024, minutes=3))
    first, second = analyze(docs, CFG), analyze(docs, CFG)
    assert codes(first) == codes(second)
    assert [(c.kind, c.monthly, c.included) for c in first.components] == [
        (c.kind, c.monthly, c.included) for c in second.components
    ]
    assert first.candidate.value == second.candidate.value


# --- checks that fail -----------------------------------------------------------------------


def test_wages_that_differ_from_w2_box_1_are_flagged_with_both_figures() -> None:
    docs = daniel()
    docs[2] = make("tax_return_1040", {**RETURN_2025, "wages": "70,500.00"}, minutes=2)
    flag = next(f for f in analyze(docs, CFG).flags if f.code == "INC-CHK-01")
    assert flag.key == "wages-2025" and flag.severity == "warning"
    assert flag.message == (
        "Form 1040 wages 70,500.00 for 2025 differ from W-2 Box 1 69,840.68 by 659.32 "
        "(tolerance 352.50)."
    )
    assert {e["field"] for e in flag.evidence} == {"wages", "box1_wages"}  # both documents


def test_wages_within_the_tolerance_are_not_flagged() -> None:
    docs = daniel()
    docs[2] = make("tax_return_1040", {**RETURN_2025, "wages": "69,841.50"}, minutes=2)
    assert "INC-CHK-01" not in by_code(analyze(docs, CFG))  # 0.82 apart, within 1.00


def test_a_different_employer_on_the_w2_is_flagged() -> None:
    docs = daniel()
    docs[1] = make("w2", {**W2_2025, "employer_name": "Northgate Plastics, LLC"}, minutes=1)
    flag = by_code(analyze(docs, CFG))["INC-CHK-02"][0]
    assert flag.message == (
        "The latest pay stub names Cedar Valley Manufacturing, Inc., but the latest W-2 names "
        "Northgate Plastics, LLC."
    )


def test_a_box_5_gap_the_box_12_codes_do_not_explain_is_a_warning() -> None:
    docs = daniel()
    docs[1] = make("w2", {**W2_2025, "box12_001_amount": "1,000.00"}, minutes=1)
    flag = next(f for f in analyze(docs, CFG).flags if f.code == "INC-CHK-03")
    assert flag.severity == "warning"
    assert flag.message == (
        "W-2 Box 5 is 4,457.92 above Box 1 for 2025, but the Box 12 deferral codes (D) add up "
        "to 1,000.00."
    )


def test_a_w2_with_no_gap_and_no_deferral_says_nothing_about_deferrals() -> None:
    docs = daniel()
    values = {**W2_2025, "box5_medicare_wages": "69,840.68"}
    del values["box12_001_code"], values["box12_001_amount"]
    docs[1] = make("w2", values, minutes=1)
    assert "INC-CHK-03" not in by_code(analyze(docs, CFG))


def test_a_fall_of_more_than_five_percent_is_a_decline_warning() -> None:
    stub = {**STUB, "gross_pay_ytd": "50,000.00"}  # 50,000 x 26 / 19 = 68,421.05, below 2025
    flag = next(f for f in analyze(daniel(stub=stub), CFG).flags if f.code == "INC-CHK-04")
    assert flag.severity == "warning"
    assert flag.message == (
        "Medicare wages fell 7.91% from 2025 (74,298.60) to the 2026 pace (68,421.05), above "
        "the 5.00% review level."
    )


def test_a_printed_frequency_that_does_not_fit_the_pay_period_is_flagged() -> None:
    stub = {**STUB, "pay_frequency": "Weekly"}
    flag = next(f for f in analyze(daniel(stub=stub), CFG).flags if f.code == "INC-W103")
    assert flag.message == "The pay stub prints Weekly pay, but its pay period is 14 days long."


def test_year_to_date_pay_that_does_not_match_the_period_is_flagged() -> None:
    stub = {**STUB, "gross_pay_ytd": "40,000.00"}
    flag = next(f for f in analyze(daniel(stub=stub), CFG).flags if f.code == "INC-W102")
    assert flag.message == (
        "Year-to-date Gross pay averages 2,105.26 per pay period, against 3,070.50 this period "
        "(difference 965.24)."
    )


def test_the_pay_date_and_the_year_to_date_must_agree_on_the_pay_period() -> None:
    stub = {**STUB, "earnings_001_ytd": "49,680.00"}  # 49,680 / 2,760 = 18, but the date says 19
    flag = next(f for f in analyze(daniel(stub=stub), CFG).flags if f.code == "INC-W104")
    assert flag.message == (
        "The pay date puts this stub in pay period 19, but year-to-date regular pay divided by "
        "this period's regular pay is 18.00."
    )


def test_an_earnings_line_that_fits_no_component_is_flagged_and_left_out() -> None:
    stub = {**STUB, "earnings_004_description": "Per diem", "earnings_004_current": "50.00"}
    outcome = analyze(daniel(stub=stub), CFG)
    flag = next(f for f in outcome.flags if f.code == "INC-W105")
    assert "'Per diem'" in flag.message and "not in the figures" in flag.message
    assert [c.kind for c in outcome.components] == ["base", "overtime", "bonus"]


# --- when a check cannot run ----------------------------------------------------------------


def test_a_pay_stub_alone_says_which_checks_could_not_run_and_still_gives_its_figures() -> None:
    outcome = analyze([make("pay_stub", STUB)], CFG)
    assert outcome.candidate.value == D("5980.00")
    cannot = {f.code: f for f in outcome.flags if f.key.endswith("-cannot")}
    assert set(cannot) == {"INC-CHK-01", "INC-CHK-02", "INC-CHK-03", "INC-CHK-04"}
    assert all(f.severity == "info" for f in cannot.values())
    assert cannot["INC-CHK-02"].message == (
        "Could not check the employer on the pay stub against the W-2: a pay stub and a W-2 "
        "not available."
    )


def test_without_a_pay_stub_nothing_is_guessed() -> None:
    outcome = analyze([make("w2", W2_2025)], CFG)
    assert outcome.components == [] and outcome.candidate.value == D("0.00")
    assert outcome.candidate.working == "No component is included = 0.00"
    assert any(f.code == "INC-W103" and f.key.endswith("-cannot") for f in outcome.flags)


def test_a_stub_with_no_frequency_and_no_period_cannot_be_turned_into_monthly_figures() -> None:
    stub = {
        k: v
        for k, v in STUB.items()
        if k not in {"pay_frequency", "pay_period_start", "pay_period_end"}
    }
    outcome = analyze([make("pay_stub", stub)], CFG)
    assert outcome.components == []
    assert next(f.code for f in outcome.flags if f.key.endswith("-cannot")) == "INC-W103"


def test_the_frequency_is_implied_by_the_period_length_when_it_is_not_printed() -> None:
    stub = {k: v for k, v in STUB.items() if k != "pay_frequency"}
    outcome = analyze([make("pay_stub", stub)], CFG)
    assert outcome.components[0].monthly == D("5980.00")  # 14 days is biweekly: 26 a year


def test_a_salary_line_without_hours_and_rate_uses_the_period_amount() -> None:
    stub = {
        k: v
        for k, v in STUB.items()
        if not k.startswith(
            ("earnings_002", "earnings_003", "earnings_001_hours", "earnings_001_rate")
        )
    }
    outcome = analyze([make("pay_stub", stub)], CFG)
    base = outcome.components[0]
    assert base.monthly == D("5980.00")  # 2,760.00 x 26 / 12
    assert base.calc.formula == "current-period amount x periods per year / 12"


# --- which documents count ------------------------------------------------------------------


def test_the_latest_stub_of_an_employer_is_the_one_used() -> None:
    older = {
        **STUB,
        "pay_period_start": "2026-08-31",
        "pay_period_end": "2026-09-13",
        "pay_date": "2026-09-18",
        "earnings_001_current": "1.00",
    }
    outcome = analyze([make("pay_stub", STUB, minutes=5), make("pay_stub", older, minutes=9)], CFG)
    assert [c.kind for c in outcome.components] == ["base", "overtime", "bonus"]
    assert outcome.components[0].current_period == D(
        "2760.00"
    )  # the later period, not the later upload


def test_a_failed_document_or_one_waiting_for_a_type_is_ignored() -> None:
    outcome = analyze(
        [make("pay_stub", STUB, status="failed"), make("pay_stub", STUB, status="type_needed")], CFG
    )
    assert outcome.components == []


def test_the_rule_based_readers_line_names_still_give_a_base_figure() -> None:
    stub = {
        "employer_name": STUB["employer_name"],
        "employee_name": STUB["employee_name"],
        "pay_frequency": "Biweekly",
        "pay_period_start": "2026-09-14",
        "pay_period_end": "2026-09-27",
        "pay_date": "2026-10-02",
        "earnings_regular_current": "2,760.00",
        "earnings_bonus_current": "105.57",
        "gross_pay_current": "3,070.50",
    }
    outcome = analyze([make("pay_stub", stub)], CFG)
    parts = {c.kind: c for c in outcome.components}
    assert parts["base"].monthly == D("5980.00")
    assert parts["bonus"].calc.formula == "current-period amount x periods per year / 12"
    assert not parts["bonus"].included


# --- wording and numbers --------------------------------------------------------------------


@pytest.mark.parametrize("variant", ["daniel", "stub only", "nothing"])
def test_no_flag_message_uses_a_decision_word(variant: str) -> None:
    docs = {
        "daniel": daniel(make("w2", W2_2024, minutes=3)),
        "stub only": [make("pay_stub", STUB)],
        "nothing": [],
    }[variant]
    for flag in analyze(docs, CFG).flags:
        assert not BLOCKED.search(flag.message), flag.message


def test_every_figure_is_an_exact_decimal() -> None:
    outcome = analyze(daniel(make("w2", W2_2024, minutes=3)), CFG)
    for calc in outcome.calcs:
        assert isinstance(calc.value, D) and calc.value.is_finite()
        assert all(isinstance(v, str) for v in calc.inputs.values())

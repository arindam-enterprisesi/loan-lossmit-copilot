"""The hardship budget's rules beyond the golden case: what is missing, adjustments, mismatches.

Pure code, no database and no model. Angela's inputs (``tests/golden/test_budget_golden.py``) are
the starting point and each test changes one thing. A figure whose inputs are missing is not
returned and an ``HB-I101`` flag says what was missing; a difference is flagged for a person to
look at and never decided (rule 3).
"""

from __future__ import annotations

import re
import uuid
from datetime import date
from decimal import Decimal as D
from pathlib import Path
from typing import Any

import pytest
import yaml

from app.services.analysis_config import THRESHOLDS_PATH, load_analysis_config
from app.services.budget import (
    BudgetInputs,
    BudgetOutcome,
    DebitLine,
    LetterFacts,
    StatedRow,
    compute_budget,
    hours_change,
    intent_key,
)
from tests.golden.test_budget_golden import CFG, REASON_KEYS, angela, inputs

BLOCKED = re.compile(r"\b(approve[sd]?|deny|denied|offer(s|ed)?|eligible|qualifies)\b", re.I)


def codes(outcome: BudgetOutcome) -> list[str]:
    return [f.code for f in outcome.flags]


def line(outcome: BudgetOutcome, category: str) -> Any:
    return next(x for x in outcome.lines if x.category == category)


def missing(outcome: BudgetOutcome) -> list[str]:
    return [f.message for f in outcome.flags if f.code == "HB-I101"]


# --- what is missing -------------------------------------------------------------------------


def test_with_no_pay_stub_there_is_no_income_and_every_measure_that_needs_it_is_left_out() -> None:
    outcome = angela(stubs=())

    assert outcome.calc("documented_net_monthly_income") is None
    assert outcome.calc("surplus_stated") is None and outcome.calc("housing_ratio") is None
    assert (
        "Cannot compute documented income: a pay stub with its gross and net pay not found."
        in missing(outcome)
    )
    assert outcome.calc("stated_expenses_total") is not None  # what does not need income still runs


def test_one_pay_stub_gives_income_but_no_change_and_says_so() -> None:
    outcome = angela(stubs=inputs().stubs[-1:])

    assert outcome.calc("documented_gross_monthly_income") is not None
    assert (
        outcome.calc("income_change") is None and outcome.calc("housing_ratio_before_cut") is None
    )
    assert outcome.calc("housing_ratio") is not None
    assert any("the change in income" in m for m in missing(outcome))


def test_with_no_application_the_stated_basis_is_not_computed_but_the_observed_one_is() -> None:
    outcome = angela(
        stated_expenses=(), stated_income=(), application_reasons=(), application_intent=None
    )

    assert outcome.calc("stated_expenses_total") is None and outcome.calc("surplus_stated") is None
    assert outcome.calc("surplus_observed").value == D("-280.00")  # type: ignore[union-attr]
    assert all(x.stated is None and not x.flagged for x in outcome.lines)
    assert any("stated expenses" in m for m in missing(outcome))
    assert outcome.calc("check_pay_vs_hours") is not None  # the checks that need no application run


def test_with_no_bank_statement_the_observed_basis_and_liquid_assets_are_not_computed() -> None:
    outcome = angela(has_statements=False, debits=(), balances=())

    assert all(x.observed is None and x.observed_calc is None for x in outcome.lines)
    assert (
        outcome.calc("observed_expenses_total") is None and outcome.calc("surplus_observed") is None
    )
    assert outcome.calc("liquid_assets") is None
    assert outcome.calc("surplus_stated").value == D("-70.00")  # type: ignore[union-attr]
    text = " ".join(missing(outcome))
    assert "observed expenses: a bank statement not found" in text
    assert "liquid assets: a bank statement's closing balance not found" in text


def test_with_no_mortgage_statement_arrears_and_the_housing_ratio_are_not_computed() -> None:
    outcome = angela(contractual_payment=None, arrears=None)

    for name in ("arrears", "housing_ratio", "liquid_assets_share_of_arrears"):
        assert outcome.calc(name) is None
    assert outcome.calc("liquid_assets") is not None
    assert any("the housing ratio" in m for m in missing(outcome))
    assert any("arrears" in m for m in missing(outcome))


def test_with_nothing_at_all_every_gap_is_reported_and_nothing_is_invented() -> None:
    outcome = compute_budget(BudgetInputs(), CFG)

    assert outcome.calcs == []
    assert all(x.stated is None and x.observed is None for x in outcome.lines)
    assert len(missing(outcome)) >= 5


# --- the observed month ----------------------------------------------------------------------


def test_a_line_is_observed_from_its_own_latest_month_with_a_debit() -> None:
    document = uuid.uuid4()
    both = (
        DebitLine(document, "p1-L1", date(2026, 7, 6), D("100.00"), "utility"),
        DebitLine(document, "p1-L2", date(2026, 9, 3), D("60.00"), "utility"),
        DebitLine(document, "p1-L3", date(2026, 9, 20), D("40.00"), "utility"),
        DebitLine(document, "p1-L4", date(2026, 7, 1), D("1720.00"), "housing payment"),
    )

    outcome = angela(debits=both)

    utilities = line(outcome, "Utilities")
    assert (utilities.observed, utilities.observed_month) == (D("100.00"), "2026-09")
    assert utilities.observed_calc.working == "September 2026: 60.00 + 40.00 = 100.00"
    assert line(outcome, "Housing (mortgage)").observed_month == "2026-07"


def test_a_line_with_no_debit_in_any_statement_is_zero_and_says_so() -> None:
    outcome = angela(debits=())

    assert line(outcome, "Utilities").observed == D("0.00")
    assert (
        line(outcome, "Utilities").observed_calc.working
        == "no debit in this line in the statements"
    )
    assert line(outcome, "Utilities").observed_month is None


def test_credit_card_payments_count_as_loan_payments_and_transfers_count_for_nothing() -> None:
    document = uuid.uuid4()

    def debit(n: int, amount: str, category: str) -> DebitLine:
        return DebitLine(document, f"p1-L{n}", date(2026, 9, n), D(amount), category)

    outcome = angela(
        debits=(
            debit(1, "410.00", "loan payment"),
            debit(2, "88.00", "credit card payment"),
            debit(3, "1000.00", "transfer out"),
            debit(4, "35.00", "other fee"),
        )
    )

    assert line(outcome, "Loan payments").observed == D("498.00")
    assert line(outcome, "Other").observed == D("35.00")
    assert sum(x.observed or 0 for x in outcome.lines) == D("533.00")


# --- stated lines ----------------------------------------------------------------------------


def test_a_stated_expense_the_budget_has_no_line_for_rolls_into_other_and_says_so() -> None:
    document = uuid.uuid4()
    extra = StatedRow(document, "Childcare", D("300.00"), ("p1-L30",))

    outcome = angela(stated_expenses=(*inputs().stated_expenses, extra))

    other = line(outcome, "Other")
    assert other.stated == D("500.00")
    assert (
        other.stated_calc.working
        == "200.00 + 300.00 = 500.00 from the application (includes Childcare)"
    )
    assert outcome.calc("stated_expenses_total").value == D("3720.00")  # type: ignore[union-attr]


def test_a_stated_line_name_is_matched_without_regard_to_case() -> None:
    document = uuid.uuid4()
    rows = (StatedRow(document, "UTILITIES", D("310.00"), ("p1-L1",)),)

    outcome = angela(stated_expenses=rows)

    assert line(outcome, "Utilities").stated == D("310.00")
    assert line(outcome, "Other").stated == D("0.00")


# --- a person's adjustment -------------------------------------------------------------------


def test_marking_a_spend_as_one_off_changes_the_observed_basis_and_clears_the_flag() -> None:
    outcome = angela(adjustments={"Other": (D("200.00"), "The 410.00 included a one-off gift.")})

    other = line(outcome, "Other")
    assert (other.observed, other.adjusted, other.effective_observed) == (
        D("410.00"),
        D("200.00"),
        D("200.00"),
    )
    assert other.adjustment_reason == "The 410.00 included a one-off gift."
    assert other.flagged is False and codes(outcome) == []
    assert outcome.calc("observed_expenses_total").value == D("3420.00")  # type: ignore[union-attr]
    assert outcome.calc("observed_expenses_total").working.endswith("(adjusted: Other)")  # type: ignore[union-attr]
    assert outcome.calc("surplus_observed").value == D("-70.00")  # type: ignore[union-attr]
    # What the statements showed is kept beside the adjustment (rule 6).
    assert other.observed_calc.value == D("410.00")


def test_an_adjustment_to_a_line_that_still_differs_is_still_flagged_at_the_adjusted_amount() -> (
    None
):
    outcome = angela(adjustments={"Other": (D("300.00"), "Part of it was a gift.")})

    assert line(outcome, "Other").flagged
    assert outcome.flags[0].message == (
        "Other: 200.00 stated against 300.00 in the statements, a difference of 100.00."
    )


# --- the checks ------------------------------------------------------------------------------


def test_a_hours_cut_that_does_not_match_the_pay_change_is_flagged_with_both_values() -> None:
    outcome = angela(letter=LetterFacts("reduction_in_income", "keep", (D("40"), D("38"))))

    assert codes(outcome) == ["HB-W101", "HB-W102"]
    flag = next(f for f in outcome.flags if f.code == "HB-W102")
    assert (
        flag.message
        == "Pay on the stubs changed by -25.00%, but the letter says hours changed by -5.00%."
    )
    check = outcome.calc("check_pay_vs_hours")
    assert check is not None and check.value == 0 and "differ by 20.00 points" in check.working


def test_a_small_difference_between_pay_and_hours_is_within_the_limit() -> None:
    outcome = angela(letter=LetterFacts("reduction_in_income", "keep", (D("40"), D("30.5"))))

    assert outcome.calc("check_pay_vs_hours").value == 1  # type: ignore[union-attr]


def test_the_limit_for_pay_against_hours_is_read_from_the_settings(tmp_path: Path) -> None:
    data = yaml.safe_load(THRESHOLDS_PATH.read_text(encoding="utf-8"))
    data["pay_vs_hours_points"]["value"] = "25"
    path = tmp_path / "thresholds.yaml"
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")

    outcome = compute_budget(
        inputs(letter=LetterFacts("reduction_in_income", "keep", (D("40"), D("38")))),
        load_analysis_config(thresholds_path=path),
    )

    assert "HB-W102" not in codes(outcome)


def test_the_applications_reason_against_the_letters() -> None:
    outcome = angela(letter=LetterFacts("unemployment", "keep", (D("40"), D("30"))))

    flag = next(f for f in outcome.flags if f.code == "HB-W103")
    assert flag.message == (
        'The application ticks "Reduction in income" '
        'but the letter\'s main reason is "unemployment".'
    )
    assert outcome.calc("check_reason_vs_letter").value == 0  # type: ignore[union-attr]


def test_a_reason_the_budget_cannot_match_to_a_category_is_not_compared() -> None:
    outcome = angela(application_reasons=("Something unusual",))

    assert outcome.calc("check_reason_vs_letter") is None


def test_the_applications_intent_against_the_letters() -> None:
    outcome = angela(letter=LetterFacts("reduction_in_income", "sell", (D("40"), D("30"))))

    flag = next(f for f in outcome.flags if f.code == "HB-W104")
    assert flag.message == 'The application says the intent is "keep" but the letter says "sell".'


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Keep the home", "keep"),
        ("I want to stay in my house", "keep"),
        ("Sell the property", "sell"),
        ("short sale", "sell"),
        ("Not sure yet", None),
        (None, None),
    ],
)
def test_the_applications_free_text_intent(text: str | None, expected: str | None) -> None:
    assert intent_key(text) == expected


def test_an_unsure_intent_is_not_compared() -> None:
    outcome = angela(application_intent="Not sure yet")

    assert outcome.calc("check_intent_vs_letter") is None and "HB-W104" not in codes(outcome)


def test_stated_income_far_from_the_stubs_is_flagged() -> None:
    rows = (StatedRow(uuid.uuid4(), "Gross monthly income", D("5000.00"), ("p1-L15",)),)

    outcome = angela(stated_income=rows)

    flag = next(f for f in outcome.flags if f.code == "HB-W105")
    assert flag.message == (
        "Stated monthly income of 5,000.00 against 4,200.00 on the pay stubs, "
        "a difference of 800.00."
    )


def test_without_the_letter_only_the_checks_that_need_no_letter_run() -> None:
    outcome = angela(letter=None)

    names = {c.name for c in outcome.calcs if c.name.startswith("check_")}
    assert names == {"check_income_stated_vs_documented"}


@pytest.mark.parametrize(
    ("texts", "expected"),
    [
        (["cut my hours from 40 to 30 a week in July"], (D("40"), D("30"))),
        (["My hours were reduced from 37.5 to 30"], (D("37.5"), D("30"))),
        (["I fell behind in August", "my employer cut my hours from 40 to 20"], (D("40"), D("20"))),
        (["the price went from 40 to 30"], None),
        (["hours from 0 to 30"], None),
        ([], None),
    ],
)
def test_the_hours_cut_is_read_from_a_sentence(
    texts: list[str], expected: tuple[D, D] | None
) -> None:
    assert hours_change(texts) == expected


# --- discipline ------------------------------------------------------------------------------


def test_no_flag_or_working_says_approve_deny_offer_eligible_or_qualifies() -> None:
    mismatched = angela(
        letter=LetterFacts("unemployment", "sell", (D("40"), D("38"))),
        stated_income=(StatedRow(uuid.uuid4(), "Gross monthly income", D("5000.00"), ()),),
    )
    texts = [f.message for o in (angela(), mismatched, angela(stubs=())) for f in o.flags]
    texts += [c.working for o in (angela(), mismatched) for c in o.calcs]

    assert texts and not [t for t in texts if BLOCKED.search(t)]


def test_the_same_inputs_always_give_the_same_budget() -> None:
    first, second = angela(), angela()

    assert [(c.name, c.value, c.working) for c in first.calcs] == [
        (c.name, c.value, c.working) for c in second.calcs
    ]
    assert [x.category for x in first.lines] == [
        "Housing (mortgage)",
        "Utilities",
        "Food and everyday",
        "Loan payments",
        "Other",
    ]


def test_the_reason_keys_come_from_the_hardship_categories() -> None:
    assert REASON_KEYS["reduction in income"] == "reduction_in_income"

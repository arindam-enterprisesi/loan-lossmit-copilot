"""Angela Whitfield's hardship budget (Feature Design 7.8), from the generated scenario.

The inputs are built from ``data/synthetic/scenarios/angela_whitfield.json`` (her stubs, the
application's stated expenses, her two statements with their labels, the mortgage statement and the
letter's reading) and every result is compared with that file's ``expected`` block as well as the
Feature Design's own figures, so the generator and the code cannot drift apart.

Income is 4,200.00 gross and 3,350.00 net a month; the stubs show a 25% drop. Expenses are 3,420.00
stated and 3,630.00 observed (housing is 1,720.00 from July, the last month the mortgage was paid);
"Other" is 200.00 stated against 410.00 observed, the one line that is flagged. The deficit is 70.00
on the stated basis and 280.00 on the observed. The housing ratio is 40.95% (30.71% before the cut).
Arrears are 5,160.00 and liquid assets 640.25, which is 12.41% of them.
"""

from __future__ import annotations

import json
import uuid
from datetime import date
from decimal import Decimal as D
from pathlib import Path
from typing import Any

import pytest

from app.prompts.schemas.hardship import load_hardship_config
from app.services.analysis_config import get_analysis_config
from app.services.budget import (
    MEASURE_ORDER,
    Balance,
    BudgetInputs,
    BudgetOutcome,
    DebitLine,
    Figure,
    LetterFacts,
    StatedRow,
    StubPay,
    compute_budget,
    hours_change,
)
from app.services.calculations import percent

SCENARIO = (
    Path(__file__).resolve().parents[3]
    / "data"
    / "synthetic"
    / "scenarios"
    / "angela_whitfield.json"
)
CFG = get_analysis_config()
DATA = json.loads(SCENARIO.read_text(encoding="utf-8"))
EXPECTED = DATA["expected"]
BUDGET = EXPECTED["budget"]
INCOME = EXPECTED["income"]
PROFILE = EXPECTED["hardship_profile"]
APPLICATION_ID, STATEMENT_ID = uuid.uuid4(), uuid.uuid4()
REASON_KEYS = {c.label.lower(): c.key for c in load_hardship_config().categories}


def docs(doc_type: str) -> list[dict[str, Any]]:
    return [d for d in DATA["documents"] if d["type"] == doc_type]


def stubs() -> tuple[StubPay, ...]:
    out = []
    for n, doc in enumerate(docs("pay_stub"), start=1):
        facts = doc["facts"]
        out.append(
            StubPay(
                document_id=uuid.uuid4(),
                pay_date=date.fromisoformat(facts["pay_date"]),
                gross=D(facts["gross_current"]),
                net=D(facts["net_current"]),
                periods_per_year=facts["periods_per_year"],
                gross_lines=(f"p1-L{10 + n}",),
                net_lines=(f"p1-L{20 + n}",),
            )
        )
    return tuple(out)


def debits() -> tuple[DebitLine, ...]:
    out = []
    for doc in docs("bank_statement"):
        document = uuid.uuid4()
        for n, t in enumerate(doc["facts"]["transactions"], start=1):
            if D(t["amount"]) < 0:
                out.append(
                    DebitLine(
                        document_id=document,
                        line_ref=f"p1-L{n}",
                        posted_on=date.fromisoformat(t["date"]),
                        amount=abs(D(t["amount"])),
                        category=t["category"],  # the generator's label stands in for a model's
                    )
                )
    return tuple(out)


def balances() -> tuple[Balance, ...]:
    newest = max(docs("bank_statement"), key=lambda d: d["facts"]["period_end"])["facts"]
    return (
        Balance(uuid.uuid4(), newest["account_last4"], D(newest["closing_balance"]), ("p2-L9",)),
    )


def inputs(**changes: Any) -> BudgetInputs:
    application = docs("mortgage_assistance_application")[0]["facts"]
    statement = docs("mortgage_statement")[0]["facts"]
    quotes = [
        "cut my hours from 40 to 30 a week in July",
        "my employer cut my hours from 40 to 30 a week in July",
    ]
    values: dict[str, Any] = {
        "stubs": stubs(),
        "stated_expenses": tuple(
            StatedRow(APPLICATION_ID, e["category"], D(e["amount"]), (f"p1-L{20 + n}",))
            for n, e in enumerate(application["expenses"])
        ),
        "stated_income": (
            StatedRow(
                APPLICATION_ID,
                "Gross monthly income",
                D(application["monthly_gross_income"]),
                ("p1-L15",),
            ),
            StatedRow(APPLICATION_ID, "Other income", D(application["other_income"]), ("p1-L16",)),
        ),
        "application_reasons": tuple(
            r["reason"] for r in application["hardship_reasons"] if r["checked"]
        ),
        "application_intent": application["intent"],
        "has_statements": True,
        "debits": debits(),
        "balances": balances(),
        "contractual_payment": Figure(D(statement["monthly_payment"]), STATEMENT_ID, ("p1-L12",)),
        "arrears": Figure(D(statement["past_due_amount"]), STATEMENT_ID, ("p1-L14",)),
        "letter": LetterFacts(PROFILE["primary_reason"], "keep", hours_change(quotes)),
        "reason_keys": REASON_KEYS,
    }
    values.update(changes)
    return BudgetInputs(**values)


def angela(**changes: Any) -> BudgetOutcome:
    return compute_budget(inputs(**changes), CFG)


def shown(outcome: BudgetOutcome, name: str) -> str:
    return percent(outcome.calc(name).value).removesuffix("%")  # type: ignore[union-attr]


# --- the golden figures ---------------------------------------------------------------------


def test_documented_income_is_4200_gross_and_3350_net_a_month() -> None:
    outcome = angela()

    assert (
        outcome.calc("documented_gross_monthly_income").value
        == D("4200.00")
        == D(INCOME["gross_monthly"])
    )  # type: ignore[union-attr]
    assert (
        outcome.calc("documented_net_monthly_income").value
        == D("3350.00")
        == D(INCOME["net_monthly"])
    )  # type: ignore[union-attr]
    assert (
        outcome.calc("documented_gross_monthly_income").working == "2,100.00 x 24 / 12 = 4,200.00"
    )  # type: ignore[union-attr]


def test_the_stubs_show_a_25_percent_drop() -> None:
    change = angela().calc("income_change")

    assert change is not None and change.value == D("-0.250000")
    assert abs(change.value) * 100 == D(INCOME["stub_drop_pct"])
    assert change.working == "(4,200.00 - 5,600.00) / 5,600.00 = -25.00%"


def test_expenses_are_3420_stated_and_3630_observed() -> None:
    outcome = angela()

    assert outcome.calc("stated_expenses_total").value == D("3420.00") == D(BUDGET["stated_total"])  # type: ignore[union-attr]
    assert (
        outcome.calc("observed_expenses_total").value == D("3630.00") == D(BUDGET["observed_total"])
    )  # type: ignore[union-attr]


def test_each_line_matches_the_scenarios_stated_and_observed_amounts() -> None:
    lines = {line.category: line for line in angela().lines}

    for category, stated in BUDGET["stated"].items():
        assert lines[category].stated == D(stated)
        assert lines[category].observed == D(BUDGET["observed"][category])


def test_housing_is_observed_from_july_the_last_month_the_mortgage_was_paid() -> None:
    lines = {line.category: line for line in angela().lines}

    assert lines["Housing (mortgage)"].observed == D("1720.00")
    assert lines["Housing (mortgage)"].observed_month == "2026-07"
    assert lines["Utilities"].observed_month == "2026-09"  # a line with debits in September
    assert lines["Housing (mortgage)"].observed_calc.working == "July 2026: 1,720.00"  # type: ignore[union-attr]


def test_only_other_is_flagged_and_the_transfer_out_is_not_an_expense() -> None:
    outcome = angela()

    flagged = [line.category for line in outcome.lines if line.flagged]
    assert flagged == ["Other"]
    other = next(line for line in outcome.lines if line.category == "Other")
    assert (other.stated, other.observed) == (
        D(BUDGET["other_stated"]),
        D(BUDGET["other_observed"]),
    )
    assert [f.code for f in outcome.flags] == ["HB-W101"]
    assert outcome.flags[0].message == (
        "Other: 200.00 stated against 410.00 in the statements, a difference of 210.00."
    )
    # September's 1,000.00 transfer to a family member is in no budget line.
    assert sum(line.observed for line in outcome.lines if line.observed) == D("3630.00")


def test_the_deficit_is_70_stated_and_280_observed() -> None:
    outcome = angela()

    assert outcome.calc("surplus_stated").value == D("-70.00") == -D(BUDGET["deficit_stated"])  # type: ignore[union-attr]
    assert outcome.calc("surplus_observed").value == D("-280.00") == -D(BUDGET["deficit_observed"])  # type: ignore[union-attr]
    assert outcome.calc("surplus_stated").working == "3,350.00 - 3,420.00 = -70.00"  # type: ignore[union-attr]
    assert outcome.calc("surplus_observed").working == "3,350.00 - 3,630.00 = -280.00"  # type: ignore[union-attr]


def test_the_housing_ratio_is_40_95_percent_and_30_71_before_the_cut() -> None:
    outcome = angela()

    assert shown(outcome, "housing_ratio") == "40.95" == BUDGET["housing_ratio_pct"]
    assert (
        shown(outcome, "housing_ratio_before_cut")
        == "30.71"
        == BUDGET["housing_ratio_before_cut_pct"]
    )
    assert outcome.calc("housing_ratio").working == "1,720.00 / 4,200.00 = 40.95%"  # type: ignore[union-attr]


def test_arrears_are_5160_and_liquid_assets_640_25_which_is_12_41_percent_of_them() -> None:
    outcome = angela()

    assert outcome.calc("arrears").value == D("5160.00") == D(BUDGET["arrears"])  # type: ignore[union-attr]
    assert outcome.calc("liquid_assets").value == D("640.25") == D(BUDGET["liquid_assets"])  # type: ignore[union-attr]
    assert (
        shown(outcome, "liquid_assets_share_of_arrears")
        == "12.41"
        == BUDGET["liquid_assets_pct_of_arrears"]
    )
    assert outcome.calc("liquid_assets_share_of_arrears").working == "640.25 / 5,160.00 = 12.41%"  # type: ignore[union-attr]


def test_the_consistency_checks_all_agree_for_angela() -> None:
    outcome = angela()

    checks = {c.name: c for c in outcome.calcs if c.name.startswith("check_")}
    assert set(checks) == {
        "check_income_stated_vs_documented",
        "check_pay_vs_hours",
        "check_reason_vs_letter",
        "check_intent_vs_letter",
    }
    assert all(c.value == 1 for c in checks.values())
    hours = checks["check_pay_vs_hours"].working
    assert "-25.00%" in hours and "40 to 30 a week" in hours and "They agree." in hours


def test_every_figure_has_its_formula_working_and_the_settings_version() -> None:
    outcome = angela()

    assert (
        [c.name for c in outcome.calcs]
        == list(MEASURE_ORDER)
        == [
            "documented_gross_monthly_income",
            "documented_net_monthly_income",
            "income_change",
            "stated_expenses_total",
            "observed_expenses_total",
            "surplus_stated",
            "surplus_observed",
            "housing_ratio",
            "housing_ratio_before_cut",
            "arrears",
            "liquid_assets",
            "liquid_assets_share_of_arrears",
            "check_income_stated_vs_documented",
            "check_pay_vs_hours",
            "check_reason_vs_letter",
            "check_intent_vs_letter",
        ]
    )
    line_calcs = [c for line in outcome.lines for c in (line.stated_calc, line.observed_calc) if c]
    assert len(line_calcs) == 10  # a stated and an observed figure for each of five lines
    for calc in outcome.calcs:
        assert isinstance(calc.value, D)  # never a float (rule 1)
        assert calc.formula and calc.working and calc.inputs
        assert calc.config_version.startswith("thresholds@")


def test_the_figures_point_at_the_lines_they_came_from() -> None:
    outcome = angela()

    assert outcome.calc("arrears").evidence[0]["field"] == "past_due_amount"  # type: ignore[union-attr]
    housing = next(line for line in outcome.lines if line.category == "Housing (mortgage)")
    assert housing.observed_calc.evidence[0]["field"] == "transaction"  # type: ignore[union-attr]
    assert housing.stated_calc.evidence[0]["field"] == "monthly_expenses"  # type: ignore[union-attr]


@pytest.mark.parametrize(
    "name",
    [
        "documented_gross_monthly_income",
        "documented_net_monthly_income",
        "income_change",
        "surplus_stated",
        "surplus_observed",
        "housing_ratio",
        "liquid_assets_share_of_arrears",
    ],
)
def test_every_headline_measure_is_a_decimal_with_its_working(name: str) -> None:
    calc = angela().calc(name)

    assert calc is not None and isinstance(calc.value, D) and calc.working

"""Asset and liability analysis (Feature 3): payroll matches, large deposits, recurring debts,
funds to close and the candidate ratios.

Pure code over plain inputs, no database and no model: the transactions arrive already labelled, as
the labelling call or a reviewer left them. Every figure is a ``Calc`` with its working (rule 1) and
the evidence it came from (rule 2); every flag is a template (rule 3: no decision wording). The
worked examples are Daniel Reyes's (Feature Design 3.8); the golden test over the generated
scenario is in ``tests/golden/test_assets_golden.py``.
"""

from __future__ import annotations

import re
import uuid
from collections.abc import Sequence
from datetime import date
from decimal import Decimal as D
from pathlib import Path
from typing import Any

import pytest
import yaml

from app.services.analysis_config import THRESHOLDS_PATH, get_analysis_config, load_analysis_config
from app.services.assets import (
    AssetInputs,
    AssetOutcome,
    IncomeInput,
    LiabilityInput,
    ObligationResult,
    ScenarioInput,
    StatementInput,
    StubInput,
    TxnInput,
    WhatIfChanges,
    WhatIfResult,
    analyze,
    ratios,
    what_if,
)

CFG = get_analysis_config()
BLOCKED = re.compile(r"\b(approve[sd]?|deny|denied|offer(s|ed)?|eligible|qualifies)\b", re.I)
DOC = uuid.uuid4()
BORROWER = ("Daniel Reyes",)


def txn(
    day: str,
    description: str,
    amount: str,
    category: str,
    *,
    direction: str | None = None,
    counterparty: str | None = None,
    ref: str | None = None,
    account: str = "6032",
    needs_review: bool = False,
    sourced: bool = False,
) -> TxnInput:
    credit = category in {
        "payroll deposit",
        "other income deposit",
        "transfer in",
        "refund",
    }
    return TxnInput(
        id=uuid.uuid4(),
        document_id=DOC,
        line_ref=ref or f"p1-L{abs(hash((day, description, amount))) % 90 + 10}",
        account_last4=account,
        posted_on=date.fromisoformat(day),
        description=description,
        amount=D(amount),
        direction=direction or ("credit" if credit else "debit"),
        category=category,
        counterparty=counterparty,
        needs_review=needs_review,
        sourced=sourced,
    )


def statement(
    period: tuple[str, str],
    closing: str | None,
    transactions: Sequence[TxnInput],
    *,
    account: str = "6032",
) -> StatementInput:
    return StatementInput(
        document_id=uuid.uuid4(),
        account_last4=account,
        period_start=date.fromisoformat(period[0]),
        period_end=date.fromisoformat(period[1]),
        opening_balance=None,
        closing_balance=D(closing) if closing is not None else None,
        closing_lines=("p3-L12",),
        transactions=tuple(transactions),
    )


def stub(net: str | None = "2033.61", *, pay_date: str = "2026-10-02", days: int = 14) -> StubInput:
    return StubInput(
        document_id=uuid.uuid4(),
        employer="Cedar Valley Manufacturing, Inc.",
        pay_date=date.fromisoformat(pay_date),
        period_days=days,
        net_pay=D(net) if net is not None else None,
        lines=("p1-L31",),
    )


def scenario(**changes: Any) -> ScenarioInput:
    values: dict[str, Any] = {
        "purpose": "purchase",
        "occupancy": "primary residence",
        "property_value": D("400000.00"),
        "loan_amount": D("360000.00"),
        "proposed_housing_payment": D("1980.00"),
        "funds_to_close": D("36500.00"),
    }
    values.update(changes)
    return ScenarioInput(**values)


def inputs(
    statements: Sequence[StatementInput] = (),
    *,
    stubs: Sequence[StubInput] = (),
    liabilities: Sequence[LiabilityInput] = (),
    loan: ScenarioInput | None = None,
    income: IncomeInput | None = None,
) -> AssetInputs:
    return AssetInputs(
        statements=tuple(statements),
        stubs=tuple(stubs),
        liabilities=tuple(liabilities),
        scenario=loan,
        income=income,
        borrower_names=BORROWER,
    )


def codes(outcome: AssetOutcome, *, info: bool = False) -> list[str]:
    """The flag codes, leaving out the info notes about missing inputs unless asked."""
    return sorted(f.code for f in outcome.flags if info or f.severity != "info")


def flag(outcome: AssetOutcome, code: str) -> Any:
    [found] = [f for f in outcome.flags if f.code == code]
    return found


# --- payroll matches (Feature Design 3.3) ---------------------------------------------------


def deposits(*dates: str, amount: str = "2033.61") -> list[TxnInput]:
    return [
        txn(d, "CEDAR VALLEY MFG PAYROLL", amount, "payroll deposit", counterparty="Cedar Valley")
        for d in dates
    ]


def test_a_payroll_deposit_matches_the_stub_by_employer_amount_and_pay_date() -> None:
    sept = statement(("2026-09-01", "2026-09-30"), "9226.32", deposits("2026-09-04", "2026-09-18"))

    outcome = analyze(inputs([sept], stubs=[stub()]), CFG)

    matched = [t for t in outcome.transactions if t.payroll_match]
    assert len(matched) == 2
    assert all(t.payroll_match.net_pay == D("2033.61") for t in matched)  # type: ignore[union-attr]
    assert "AL-W104" not in codes(outcome)


def test_a_deposit_a_few_days_off_a_pay_date_still_matches_but_not_more_than_three() -> None:
    near = statement(
        ("2026-09-01", "2026-09-30"), None, deposits("2026-09-07")
    )  # 3 days after 09-04
    far = statement(("2026-09-01", "2026-09-30"), None, deposits("2026-09-08"))  # 4 days after

    assert analyze(inputs([near], stubs=[stub()]), CFG).transactions[0].payroll_match
    assert analyze(inputs([far], stubs=[stub()]), CFG).transactions[0].payroll_match is None


def test_the_printed_net_pay_does_not_match_the_deposits_and_says_so() -> None:
    # Daniel's stub prints net pay 2,083.61 (the true figure is 2,033.61). Until a reviewer
    # corrects it, the deposits of 2,033.61 do not match, and each one is flagged.
    sept = statement(("2026-09-01", "2026-09-30"), None, deposits("2026-09-04", "2026-09-18"))

    outcome = analyze(inputs([sept], stubs=[stub("2083.61")]), CFG)

    assert [t.payroll_match for t in outcome.transactions] == [None, None]
    assert codes(outcome) == ["AL-W104", "AL-W104"]
    assert sorted(f.message for f in outcome.flags if f.code == "AL-W104") == [
        "Payroll deposit of 2,033.61 on 2026-09-04 does not match a pay stub.",
        "Payroll deposit of 2,033.61 on 2026-09-18 does not match a pay stub.",
    ]


def test_a_deposit_from_another_employer_is_not_a_match() -> None:
    other = txn("2026-09-04", "ACME PAYROLL", "2033.61", "payroll deposit")

    outcome = analyze(
        inputs([statement(("2026-09-01", "2026-09-30"), None, [other])], stubs=[stub()]), CFG
    )

    assert outcome.transactions[0].payroll_match is None


def test_with_no_pay_stub_nothing_is_matched_and_nothing_is_flagged_as_unmatched() -> None:
    sept = statement(("2026-09-01", "2026-09-30"), None, deposits("2026-09-04"))

    outcome = analyze(inputs([sept]), CFG)

    assert outcome.transactions[0].payroll_match is None
    assert "AL-W104" not in codes(outcome)  # there was nothing to match against


# --- large deposits and fees ----------------------------------------------------------------


def test_a_large_deposit_from_an_individual_is_flagged_with_the_feature_designs_message() -> None:
    zelle = txn(
        "2026-09-22",
        "ZELLE FROM PATRICIA OWENS REF 8841",
        "2000.00",
        "transfer in",
        counterparty="Patricia Owens",
    )

    outcome = analyze(inputs([statement(("2026-09-01", "2026-09-30"), None, [zelle])]), CFG)

    assert flag(outcome, "AL-W101").message == (
        "Large deposit of 2,000.00 on 2026-09-22 — source may need documenting under program rules."
    )
    assert flag(outcome, "AL-W101").severity == "warning"
    assert outcome.transactions[0].large_deposit


@pytest.mark.parametrize(
    ("amount", "category", "counterparty", "flagged"),
    [
        ("999.99", "transfer in", "Patricia Owens", False),  # under the minimum
        ("1000.00", "transfer in", "Patricia Owens", True),  # the minimum itself
        ("5000.00", "payroll deposit", "Cedar Valley", False),  # payroll is not a large deposit
        ("5000.00", "transfer in", "Daniel Reyes", False),  # between the borrower's own accounts
        ("1500.00", "refund", "Amazon", True),
        ("1500.00", "other income deposit", None, True),
    ],
)
def test_which_credits_are_large_deposits(
    amount: str, category: str, counterparty: str | None, flagged: bool
) -> None:
    credit = txn("2026-09-22", "DEPOSIT", amount, category, counterparty=counterparty)

    outcome = analyze(inputs([statement(("2026-09-01", "2026-09-30"), None, [credit])]), CFG)

    assert ("AL-W101" in codes(outcome)) is flagged


def test_a_deposit_a_person_marked_as_sourced_is_not_flagged_again() -> None:
    zelle = txn(
        "2026-09-22",
        "ZELLE FROM PATRICIA OWENS",
        "2000.00",
        "transfer in",
        counterparty="Patricia Owens",
        sourced=True,
    )

    outcome = analyze(inputs([statement(("2026-09-01", "2026-09-30"), None, [zelle])]), CFG)

    assert "AL-W101" not in codes(outcome)
    assert outcome.transactions[0].large_deposit and outcome.transactions[0].sourced


def test_an_overdraft_or_returned_item_fee_is_flagged() -> None:
    fee = txn("2026-09-03", "OVERDRAFT FEE", "35.00", "overdraft or returned-item fee")

    outcome = analyze(inputs([statement(("2026-09-01", "2026-09-30"), None, [fee])]), CFG)

    assert (
        flag(outcome, "AL-W102").message == "Overdraft or returned-item fee of 35.00 on 2026-09-03."
    )


def test_lines_the_labeller_could_not_place_are_counted_for_review() -> None:
    unsure = [
        txn("2026-09-03", "XQ 9981", "12.00", "other", needs_review=True),
        txn("2026-09-04", "ZZ 12", "9.00", "other", needs_review=True),
    ]

    outcome = analyze(inputs([statement(("2026-09-01", "2026-09-30"), None, unsure)]), CFG)

    assert (
        flag(outcome, "AL-W107").message == "2 transactions could not be labelled and need review."
    )


# --- recurring debts and the credit report --------------------------------------------------


def bank_debts() -> list[StatementInput]:
    rows = (
        ("LAKESHORE AUTO FINANCE", "420.00", "loan payment", "Lakeshore Auto Finance"),
        ("NORTHGATE CARD PAYMENT", "88.00", "credit card payment", "Northgate Card"),
    )
    return [
        statement(
            (f"2026-{month}-01", f"2026-{month}-28"),
            None,
            [txn(f"2026-{month}-05", d, a, c, counterparty=p) for d, a, c, p in rows]
            + [
                txn(
                    f"2026-{month}-01",
                    "OAKMONT APARTMENTS RENT",
                    "1425.00",
                    "housing payment",
                    counterparty="Oakmont Apartments",
                )
            ],
        )
        for month in ("08", "09")
    ]


def tradeline(creditor: str, payment: str, kind: str = "installment") -> LiabilityInput:
    return LiabilityInput(
        document_id=uuid.uuid4(),
        creditor=creditor,
        kind=kind,
        balance=D("1000.00"),
        monthly_payment=D(payment),
        lines=("p2-L9",),
    )


def test_the_same_payee_in_two_months_within_a_dollar_is_a_recurring_debt() -> None:
    outcome = analyze(inputs(bank_debts()), CFG)

    by = {o.creditor: o for o in outcome.obligations}
    assert by["Lakeshore Auto Finance"].monthly_payment == D("420.00")
    assert by["Lakeshore Auto Finance"].source == "bank"
    assert by["Northgate Card"].monthly_payment == D("88.00")


def test_one_month_is_not_recurring() -> None:
    only_august = bank_debts()[:1]

    assert analyze(inputs(only_august), CFG).obligations == []


def test_amounts_more_than_a_dollar_apart_are_not_one_recurring_debt() -> None:
    august = statement(
        ("2026-08-01", "2026-08-28"),
        None,
        [
            txn(
                "2026-08-05",
                "CARD PAYMENT",
                "88.00",
                "credit card payment",
                counterparty="Northgate Card",
            )
        ],
    )
    september = statement(
        ("2026-09-01", "2026-09-28"),
        None,
        [
            txn(
                "2026-09-05",
                "CARD PAYMENT",
                "90.50",
                "credit card payment",
                counterparty="Northgate Card",
            )
        ],
    )

    assert analyze(inputs([august, september]), CFG).obligations == []


def test_rent_on_a_purchase_of_a_primary_residence_does_not_count() -> None:
    outcome = analyze(inputs(bank_debts(), loan=scenario()), CFG)

    rent = next(o for o in outcome.obligations if o.creditor == "Oakmont Apartments")
    assert rent.counts_toward_dti is False
    assert rent.reason == "Current rent on a purchase of a primary residence."


def test_rent_counts_when_the_loan_is_not_a_purchase_of_a_primary_residence() -> None:
    outcome = analyze(inputs(bank_debts(), loan=scenario(purpose="refinance")), CFG)

    rent = next(o for o in outcome.obligations if o.creditor == "Oakmont Apartments")
    assert rent.counts_toward_dti is True


def test_a_debt_on_both_the_bank_statements_and_the_credit_report_is_one_obligation() -> None:
    liabilities = [
        tradeline("Lakeshore Auto Finance", "420.00"),
        tradeline("Northgate Card", "88.00", "revolving"),
    ]

    outcome = analyze(inputs(bank_debts(), liabilities=liabilities), CFG)

    by = {o.creditor: o for o in outcome.obligations}
    assert by["Lakeshore Auto Finance"].source == "both"
    assert [o.creditor for o in outcome.obligations].count("Lakeshore Auto Finance") == 1
    assert "AL-W103" not in codes(outcome)


def test_a_credit_report_debt_the_bank_statements_do_not_show_still_counts() -> None:
    # Harbor Retail Card is on the credit report only (35.00 a month).
    liabilities = [tradeline("Harbor Retail Card", "35.00", "revolving")]

    outcome = analyze(inputs(bank_debts(), liabilities=liabilities), CFG)

    harbor = next(o for o in outcome.obligations if o.creditor == "Harbor Retail Card")
    assert (harbor.source, harbor.counts_toward_dti, harbor.monthly_payment) == (
        "credit_report",
        True,
        D("35.00"),
    )


def test_a_recurring_debt_missing_from_a_credit_report_is_flagged() -> None:
    liabilities = [tradeline("Lakeshore Auto Finance", "420.00")]  # Northgate is not on the report

    outcome = analyze(inputs(bank_debts(), liabilities=liabilities), CFG)

    assert flag(outcome, "AL-W103").message == (
        "Recurring payment to Northgate Card (88.00 a month) is in the bank statements but "
        "not on the credit report."
    )


def test_with_no_credit_report_nothing_is_reconciled_and_nothing_is_flagged() -> None:
    outcome = analyze(inputs(bank_debts()), CFG)

    assert "AL-W103" not in codes(outcome)
    assert {o.source for o in outcome.obligations} == {"bank"}


def test_a_credit_report_debt_with_no_payment_does_not_count() -> None:
    outcome = analyze(inputs([], liabilities=[tradeline("Old Card", "0.00", "revolving")]), CFG)

    [old] = outcome.obligations
    assert (
        old.counts_toward_dti is False
        and old.reason == "The credit report shows no monthly payment."
    )


# --- funds to close -------------------------------------------------------------------------


def test_documented_assets_are_the_latest_closing_balance_of_each_account() -> None:
    august = statement(("2026-08-01", "2026-08-31"), "6455.13", [])
    september = statement(("2026-09-01", "2026-09-30"), "9226.32", [])
    savings = statement(("2026-09-01", "2026-09-30"), "1000.00", [], account="1188")

    outcome = analyze(inputs([august, september, savings]), CFG)

    assert outcome.calc("documented_assets").value == D("10226.32")  # 9,226.32 + 1,000.00
    assert [(a.account_last4, a.closing_balance) for a in outcome.accounts] == [
        ("1188", D("1000.00")),
        ("6032", D("9226.32")),
    ]


def test_the_shortfall_is_what_is_needed_less_what_is_documented() -> None:
    september = statement(("2026-09-01", "2026-09-30"), "9226.32", [])

    outcome = analyze(inputs([september], loan=scenario()), CFG)

    assert outcome.calc("funds_to_close").value == D("36500.00")
    assert outcome.calc("funds_shortfall").value == D("27273.68")
    assert outcome.calc("funds_shortfall").working == "36,500.00 - 9,226.32 = 27,273.68"
    assert flag(outcome, "AL-W105").message == (
        "Documented assets of 9,226.32 are 27,273.68 short of the 36,500.00 needed to close."
    )


def test_when_assets_cover_the_funds_the_shortfall_is_zero_and_nothing_is_flagged() -> None:
    september = statement(("2026-09-01", "2026-09-30"), "40000.00", [])

    outcome = analyze(inputs([september], loan=scenario()), CFG)

    assert outcome.calc("funds_shortfall").value == D("0.00")
    assert "AL-W105" not in codes(outcome)


def test_a_statement_with_no_closing_balance_says_so_instead_of_guessing() -> None:
    outcome = analyze(
        inputs([statement(("2026-09-01", "2026-09-30"), None, [])], loan=scenario()), CFG
    )

    assert outcome.calc("documented_assets") is None
    assert "AL-I101" in codes(outcome, info=True)
    assert any("closing balance" in f.message for f in outcome.flags if f.code == "AL-I101")


# --- the ratios -----------------------------------------------------------------------------


INCOME = IncomeInput(
    candidate_monthly=D("5980.00"),
    excluded_monthly={"overtime": D("444.41"), "bonus": D("228.34")},
)


def test_daniels_candidate_ratios() -> None:
    september = statement(("2026-09-01", "2026-09-30"), "9226.32", [])
    liabilities = [
        tradeline("Lakeshore Auto Finance", "420.00"),
        tradeline("Brightpath Student Loan Servicing", "110.00"),
        tradeline("Northgate Card", "88.00", "revolving"),
        tradeline("Cardinal Rewards Visa", "40.00", "revolving"),
        tradeline("Harbor Retail Card", "35.00", "revolving"),
    ]

    outcome = analyze(
        inputs([september], liabilities=liabilities, loan=scenario(), income=INCOME), CFG
    )

    assert outcome.calc("monthly_obligations").value == D("693.00")
    assert outcome.calc("front_end_ratio").value == D("0.331104")
    assert outcome.calc("front_end_ratio").working == "1,980.00 / 5,980.00 = 33.11%"
    assert outcome.calc("dti").working == "(1,980.00 + 693.00) / 5,980.00 = 44.70%"
    assert outcome.calc("dti").value == D("0.446990")
    assert outcome.calc("ltv").working == "360,000.00 / 400,000.00 = 90.00%"
    assert outcome.calc("dti_with_overtime").working == "(1,980.00 + 693.00) / 6,424.41 = 41.61%"
    # 44.70% is above the illustrative 43% review level, and the message says it is for review.
    assert flag(outcome, "AL-W106").message == "DTI 44.70% is above the review level of 43%."


def test_a_dti_at_or_under_the_review_level_raises_no_flag() -> None:
    outcome = analyze(
        inputs([], liabilities=[tradeline("Card", "100.00")], loan=scenario(), income=INCOME), CFG
    )

    assert outcome.calc("dti").value < D("0.43")
    assert "AL-W106" not in codes(outcome)


def test_the_prd_samples_dti_and_ltv_are_the_formulas_arithmetic() -> None:
    # The PRD's inputs are not in the repository, only its results: 41.21% DTI on a monthly
    # income of 4,853.33 (the base pay figure) means 2,000.00 of housing and debts, and 80.00% LTV
    # is a loan of 320,000.00 on 400,000.00. These pin the formulas; they are not Daniel's case.
    calcs = ratios(
        scenario=scenario(proposed_housing_payment=D("1500.00"), loan_amount=D("320000.00")),
        income=IncomeInput(candidate_monthly=D("4853.33"), excluded_monthly={}),
        obligations_monthly=D("500.00"),
        version="thresholds@test",
        review_level=D("0.43"),
    )

    by = {c.name: c for c in calcs}
    assert by["dti"].working == "(1,500.00 + 500.00) / 4,853.33 = 41.21%"
    assert by["ltv"].working == "320,000.00 / 400,000.00 = 80.00%"


def test_ratios_need_a_scenario_and_an_income_and_say_what_is_missing() -> None:
    no_scenario = analyze(inputs([], income=INCOME), CFG)
    no_income = analyze(inputs([], loan=scenario()), CFG)

    assert no_scenario.calc("dti") is None and "AL-I101" in codes(no_scenario, info=True)
    assert "loan scenario" in flag(no_scenario, "AL-I101").message
    assert no_income.calc("front_end_ratio") is None and "AL-I101" in codes(no_income, info=True)
    assert any("income" in f.message for f in no_income.flags if f.code == "AL-I101")
    assert no_income.calc("ltv").value == D("0.900000")  # LTV needs no income


def test_a_zero_or_missing_income_never_divides() -> None:
    zero = IncomeInput(candidate_monthly=D("0.00"), excluded_monthly={})

    outcome = analyze(inputs([], loan=scenario(), income=zero), CFG)

    assert outcome.calc("dti") is None and "AL-I101" in codes(outcome, info=True)


# --- rules 1, 2 and 3 -----------------------------------------------------------------------


def full_outcome() -> AssetOutcome:
    august, september = bank_debts()
    zelle = txn(
        "2026-09-22",
        "ZELLE FROM PATRICIA OWENS",
        "2000.00",
        "transfer in",
        counterparty="Patricia Owens",
    )
    september = statement(("2026-09-01", "2026-09-30"), "9226.32", [*september.transactions, zelle])
    return analyze(
        inputs(
            [august, september],
            stubs=[stub()],
            liabilities=[tradeline("Harbor Retail Card", "35.00")],
            loan=scenario(),
            income=INCOME,
        ),
        CFG,
    )


def test_every_figure_has_its_formula_working_inputs_and_the_settings_version() -> None:
    outcome = full_outcome()

    assert {c.name for c in outcome.calcs} >= {
        "documented_assets",
        "funds_to_close",
        "funds_shortfall",
        "monthly_obligations",
        "front_end_ratio",
        "dti",
        "ltv",
    }
    for calc in outcome.calcs:
        assert isinstance(calc.value, D)  # never a float (rule 1)
        assert calc.formula and calc.working and calc.inputs
        assert calc.config_version == "thresholds@2026-11-24.1"


def test_the_assets_figure_points_at_the_statement_line_it_came_from() -> None:
    evidence = full_outcome().calc("documented_assets").evidence

    assert evidence and evidence[0]["line_ids"] == ["p3-L12"]  # rule 2


def test_no_flag_or_working_uses_decision_wording() -> None:
    outcome = full_outcome()

    texts = [f.message for f in outcome.flags] + [c.working for c in outcome.calcs]
    texts += [o.reason for o in outcome.obligations]
    assert texts and all(not BLOCKED.search(t) for t in texts)


# --- settings come from the file, not the code ----------------------------------------------


def test_the_large_deposit_minimum_is_read_from_the_settings(tmp_path: Path) -> None:
    data = yaml.safe_load(THRESHOLDS_PATH.read_text(encoding="utf-8"))
    data["large_deposit_minimum"]["value"] = "3000.00"
    path = tmp_path / "thresholds.yaml"
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    zelle = txn("2026-09-22", "ZELLE", "2000.00", "transfer in", counterparty="Patricia Owens")

    outcome = analyze(
        inputs([statement(("2026-09-01", "2026-09-30"), None, [zelle])]),
        load_analysis_config(thresholds_path=path),
    )

    assert "AL-W101" not in codes(outcome)


# --- what if --------------------------------------------------------------------------------


def stored_obligations() -> list[ObligationResult]:
    def debt(creditor: str, payment: str, kind: str = "installment") -> ObligationResult:
        return ObligationResult(creditor, kind, D(payment), None, "credit_report", True, "x")

    return [
        debt("Lakeshore Auto Finance", "420.00"),
        debt("Brightpath Student Loan Servicing", "110.00"),
        debt("Northgate Card", "88.00", "revolving"),
        debt("Cardinal Rewards Visa", "40.00", "revolving"),
        debt("Harbor Retail Card", "35.00", "revolving"),
    ]


def try_what_if(changes: WhatIfChanges, assets: str | None = "9226.32") -> WhatIfResult:
    return what_if(
        scenario=scenario(),
        income=INCOME,
        obligations=stored_obligations(),
        documented_assets=D(assets) if assets else None,
        changes=changes,
        version=CFG.calc_version("thresholds"),
        review_level=CFG.thresholds.dti_review_level.value,
    )


def test_a_what_if_with_no_changes_gives_the_stored_figures() -> None:
    result = try_what_if(WhatIfChanges())

    assert result.changed == {}
    assert result.calc("dti").working == "(1,980.00 + 693.00) / 5,980.00 = 44.70%"
    assert result.calc("ltv").value == D("0.9")
    assert result.calc("funds_shortfall").value == D("27273.68")


def test_paying_off_a_loan_takes_its_payment_out_of_the_dti() -> None:
    result = try_what_if(WhatIfChanges(drop_obligations=("lakeshore auto finance",)))

    assert result.calc("monthly_obligations").working == "110.00 + 88.00 + 40.00 + 35.00 = 273.00"
    assert result.calc("dti").working == "(1,980.00 + 273.00) / 5,980.00 = 37.68%"
    assert result.unmatched == []


def test_a_name_that_matches_no_obligation_is_reported_and_changes_nothing() -> None:
    result = try_what_if(WhatIfChanges(drop_obligations=("Nobody Bank",)))

    assert result.unmatched == ["Nobody Bank"]
    assert result.calc("monthly_obligations").value == D("693.00")


def test_a_smaller_loan_and_a_new_payment_change_ltv_and_dti() -> None:
    result = try_what_if(
        WhatIfChanges(loan_amount=D("320000.00"), extra_obligation_monthly=D("150.00"))
    )

    assert result.calc("ltv").working == "320,000.00 / 400,000.00 = 80.00%"
    assert result.calc("monthly_obligations").value == D("843.00")
    assert result.changed == {"loan_amount": "320000.00", "extra_obligation_monthly": "150.00"}


def test_more_documented_funds_remove_the_shortfall_and_other_income_moves_the_ratios() -> None:
    result = try_what_if(WhatIfChanges(funds_to_close=D("9000.00"), monthly_income=D("6500.00")))

    assert result.calc("funds_shortfall").working == "9,226.32 covers 9,000.00: no shortfall"
    assert result.calc("front_end_ratio").working == "1,980.00 / 6,500.00 = 30.46%"


def test_a_what_if_never_changes_what_it_was_given() -> None:
    held = stored_obligations()
    try_what_if(WhatIfChanges(drop_obligations=("Northgate Card",)))

    assert held == stored_obligations()


def test_a_what_if_figure_has_working_and_no_decision_wording() -> None:
    result = try_what_if(WhatIfChanges(loan_amount=D("300000.00")))

    assert all(c.working and c.formula for c in result.calcs)
    assert not BLOCKED.search(" ".join(c.working + c.formula for c in result.calcs))


# --- what the run stores: matches, large deposits and a person's inclusion of a debt ---------


def test_each_payroll_match_and_large_deposit_is_a_figure_pointing_at_its_line() -> None:
    zelle = txn(
        "2026-09-22",
        "ZELLE FROM PATRICIA OWENS",
        "2000.00",
        "transfer in",
        counterparty="Patricia Owens",
        ref="p2-L7",
    )
    lines = [*deposits("2026-09-18", "2026-10-02"), zelle]
    outcome = analyze(
        inputs([statement(("2026-09-01", "2026-09-30"), "9226.32", lines)], stubs=[stub()]), CFG
    )

    matches = [c for c in outcome.calcs if c.name == "payroll_match"]
    large = [c for c in outcome.calcs if c.name == "large_deposit"]
    assert len(matches) == 2 and len(large) == 1
    assert matches[0].evidence[0]["field"] == "transaction"
    assert matches[0].evidence[1]["field"] == "net_pay_current"  # the stub it matched (rule 2)
    assert large[0].evidence[0]["line_ids"] == ["p2-L7"]


def test_a_person_excluding_a_debt_changes_the_total_and_keeps_the_systems_answer() -> None:
    liabilities = [
        tradeline("Lakeshore Auto Finance", "420.00"),
        tradeline("Northgate Card", "88.00"),
    ]
    base = inputs([statement(("2026-09-01", "2026-09-30"), "1000.00", [])], liabilities=liabilities)
    changed = AssetInputs(
        base.statements,
        base.stubs,
        base.liabilities,
        base.scenario,
        base.income,
        base.borrower_names,
        obligation_overrides=(("lakeshore auto finance", False),),
    )

    outcome = analyze(changed, CFG)

    auto = next(o for o in outcome.obligations if o.creditor.startswith("Lakeshore"))
    assert (auto.counts_toward_dti, auto.system_counts) == (False, True)
    assert outcome.calc("monthly_obligations").value == D("88.00")
    card = next(o for o in outcome.obligations if o.creditor.startswith("Northgate"))
    assert (card.counts_toward_dti, card.system_counts) == (True, None)


def test_an_override_that_agrees_with_the_system_changes_nothing() -> None:
    liabilities = [tradeline("Northgate Card", "88.00")]
    base = inputs([statement(("2026-09-01", "2026-09-30"), "1000.00", [])], liabilities=liabilities)
    same = AssetInputs(
        *(getattr(base, f) for f in ("statements", "stubs", "liabilities", "scenario", "income")),
        base.borrower_names,
        obligation_overrides=(("Northgate Card", True),),
    )

    [card] = analyze(same, CFG).obligations

    assert (card.counts_toward_dti, card.system_counts) == (True, None)

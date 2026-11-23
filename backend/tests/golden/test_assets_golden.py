"""Daniel Reyes's asset and liability figures (Feature Design 3.8), from the generated scenario.

The inputs are built from ``data/synthetic/scenarios/daniel_reyes.json`` (his statements with their
labels, his pay stub, his credit report's tradelines and the loan scenario) and the results are
compared with that file's ``expected`` block as well as with the Feature Design's own figures, so
the generator and the analysis cannot drift apart.

The pay stub prints a net pay of 2,083.61 (the true figure is 2,033.61: demo step 3 corrects it).
The matching runs on the corrected value; the uncorrected one must not match.
"""

from __future__ import annotations

import json
import uuid
from datetime import date
from decimal import Decimal as D
from pathlib import Path
from typing import Any

import pytest

from app.services.analysis_config import get_analysis_config
from app.services.assets import (
    AssetInputs,
    IncomeInput,
    LiabilityInput,
    ScenarioInput,
    StatementInput,
    StubInput,
    TxnInput,
    analyze,
)
from app.services.calculations import percent

SCENARIO = (
    Path(__file__).resolve().parents[3] / "data" / "synthetic" / "scenarios" / "daniel_reyes.json"
)
CFG = get_analysis_config()
DATA = json.loads(SCENARIO.read_text(encoding="utf-8"))
EXPECTED = DATA["expected"]["assets_liabilities"]
INCOME = DATA["expected"]["income"]


def docs(doc_type: str) -> list[dict[str, Any]]:
    return [d for d in DATA["documents"] if d["type"] == doc_type]


def statements() -> list[StatementInput]:
    out = []
    for doc in docs("bank_statement"):
        facts, document = doc["facts"], uuid.uuid4()
        rows = tuple(
            TxnInput(
                id=uuid.uuid4(),
                document_id=document,
                line_ref=f"p1-L{number}",
                account_last4=facts["account_last4"],
                posted_on=date.fromisoformat(t["date"]),
                description=t["description"],
                amount=abs(D(t["amount"])),
                direction="credit" if D(t["amount"]) > 0 else "debit",
                category=t["category"],  # the generator's label stands in for the model's
                counterparty=t["counterparty"],
            )
            for number, t in enumerate(facts["transactions"], start=1)
        )
        out.append(
            StatementInput(
                document_id=document,
                account_last4=facts["account_last4"],
                period_start=date.fromisoformat(facts["period_start"]),
                period_end=date.fromisoformat(facts["period_end"]),
                opening_balance=D(facts["opening_balance"]),
                closing_balance=D(facts["closing_balance"]),
                closing_lines=("p3-L12",),
                transactions=rows,
            )
        )
    return out


def stub(*, corrected: bool = True) -> StubInput:
    facts = docs("pay_stub")[0]["facts"]
    net = facts["net_current"] if corrected else facts["printed_net_current"]
    return StubInput(
        document_id=uuid.uuid4(),
        employer=facts["employer"]["name"],
        pay_date=date.fromisoformat(facts["pay_date"]),
        period_days=14,  # biweekly
        net_pay=D(net),
        lines=("p1-L31",),
    )


def liabilities() -> list[LiabilityInput]:
    document = uuid.uuid4()
    return [
        LiabilityInput(
            document_id=document,
            creditor=t["creditor"],
            kind=t["account_type"],
            balance=D(t["balance"]),
            monthly_payment=D(t["monthly_payment"]),
            lines=(f"p2-L{n}",),
        )
        for n, t in enumerate(docs("credit_report")[0]["facts"]["tradelines"], start=9)
    ]


def scenario() -> ScenarioInput:
    s = DATA["loan_scenario"]
    return ScenarioInput(
        purpose=s["purpose"],
        occupancy=s["occupancy"],
        property_value=D(s["property_value"]),
        loan_amount=D(s["loan_amount"]),
        proposed_housing_payment=D(s["proposed_housing_payment"]),
        funds_to_close=D(s["funds_needed_to_close"]),
    )


def daniel(*, with_credit_report: bool = True, corrected: bool = True) -> Any:
    inputs = AssetInputs(
        statements=tuple(statements()),
        stubs=(stub(corrected=corrected),),
        liabilities=tuple(liabilities()) if with_credit_report else (),
        scenario=scenario(),
        income=IncomeInput(
            candidate_monthly=D(INCOME["candidate_monthly"]),
            excluded_monthly={
                "overtime": D(INCOME["overtime_monthly"]),
                "bonus": D(INCOME["bonus_monthly"]),
            },
        ),
        borrower_names=("Daniel Reyes",),
    )
    return analyze(inputs, CFG)


def shown(outcome: Any, name: str) -> str:
    return percent(outcome.calc(name).value).removesuffix("%")


# --- the golden figures ---------------------------------------------------------------------


def test_documented_assets_and_the_shortfall() -> None:
    outcome = daniel()

    assert (
        outcome.calc("documented_assets").value == D("9226.32") == D(EXPECTED["documented_assets"])
    )
    assert outcome.calc("funds_to_close").value == D("36500.00")
    assert outcome.calc("funds_shortfall").value == D("27273.68") == D(EXPECTED["shortfall"])
    assert outcome.calc("funds_shortfall").working == "36,500.00 - 9,226.32 = 27,273.68"


def test_obligations_are_693_a_month_from_five_debts() -> None:
    outcome = daniel()

    assert (
        outcome.calc("monthly_obligations").value
        == D("693.00")
        == D(EXPECTED["obligations_monthly"])
    )
    counted = {o.creditor: o.monthly_payment for o in outcome.obligations if o.counts_toward_dti}
    assert counted == {
        "Lakeshore Auto Finance": D("420.00"),
        "Brightpath Student Loan Servicing": D("110.00"),
        "Northgate Card": D("88.00"),
        "Cardinal Rewards Visa": D("40.00"),
        "Harbor Retail Card": D("35.00"),
    }
    sources = {o.creditor: o.source for o in outcome.obligations}
    assert sources["Harbor Retail Card"] == "credit_report"  # not paid from this account
    assert sources["Lakeshore Auto Finance"] == "both"
    rent = next(o for o in outcome.obligations if o.creditor == "Oakmont Apartments")
    assert rent.counts_toward_dti is False  # current rent on a purchase of a primary residence


def test_the_candidate_ratios_match_the_feature_design_and_the_scenario() -> None:
    outcome = daniel()

    assert shown(outcome, "front_end_ratio") == "33.11" == EXPECTED["front_end_ratio_pct"]
    assert shown(outcome, "dti") == "44.70" == EXPECTED["dti_pct"]
    assert shown(outcome, "ltv") == "90.00" == EXPECTED["ltv_pct"]
    assert shown(outcome, "dti_with_overtime") == "41.61" == EXPECTED["dti_with_overtime_pct"]


def test_the_working_can_be_followed_by_hand() -> None:
    outcome = daniel()

    assert outcome.calc("front_end_ratio").working == "1,980.00 / 5,980.00 = 33.11%"
    assert outcome.calc("dti").working == "(1,980.00 + 693.00) / 5,980.00 = 44.70%"
    assert outcome.calc("dti_with_overtime").working == "(1,980.00 + 693.00) / 6,424.41 = 41.61%"


def test_both_september_paychecks_match_the_stub_and_the_transfer_is_the_one_large_deposit() -> (
    None
):
    outcome = daniel()

    matched = {
        (t.input.posted_on.isoformat(), str(t.input.amount))
        for t in outcome.transactions
        if t.payroll_match
    }
    for expected in EXPECTED["payroll_matches"]:
        assert (expected["date"], expected["amount"]) in matched
    large = [t for t in outcome.transactions if t.large_deposit]
    assert [
        (t.input.posted_on.isoformat(), str(t.input.amount), t.input.counterparty) for t in large
    ] == [
        (
            EXPECTED["large_deposit"]["date"],
            EXPECTED["large_deposit"]["amount"],
            EXPECTED["large_deposit"]["counterparty"],
        )
    ]


def test_the_flags_are_the_shortfall_the_transfer_and_the_dti_review() -> None:
    outcome = daniel()

    assert sorted(f.code for f in outcome.flags if f.severity != "info") == [
        "AL-W101",
        "AL-W105",
        "AL-W106",
    ]
    messages = {f.code: f.message for f in outcome.flags}
    assert messages["AL-W101"] == (
        "Large deposit of 2,000.00 on 2026-09-22 — source may need documenting under program rules."
    )
    assert messages["AL-W106"] == "DTI 44.70% is above the review level of 43%."


# --- what the demo shows until the credit report is read -------------------------------------


def test_without_a_credit_report_only_the_four_bank_debts_are_found() -> None:
    # The credit report has no extract schema yet, so the live demo reads only the bank statements:
    # 658.00 a month (Harbor Retail Card's 35.00 is credit-report only) and a DTI of 44.11%.
    outcome = daniel(with_credit_report=False)

    assert outcome.calc("monthly_obligations").value == D("658.00")
    assert shown(outcome, "dti") == "44.11"
    assert "AL-W103" not in [f.code for f in outcome.flags]  # nothing to reconcile with


def test_the_uncorrected_net_pay_matches_nothing_and_each_deposit_says_so() -> None:
    outcome = daniel(corrected=False)

    assert not any(t.payroll_match for t in outcome.transactions)
    unmatched = [f for f in outcome.flags if f.code == "AL-W104"]
    assert len(unmatched) == 4  # four payroll deposits across August and September


@pytest.mark.parametrize("name", ["front_end_ratio", "dti", "ltv", "dti_with_overtime"])
def test_every_ratio_is_a_decimal_with_its_working(name: str) -> None:
    calc = daniel().calc(name)

    assert (
        isinstance(calc.value, D) and calc.working and calc.config_version.startswith("thresholds@")
    )

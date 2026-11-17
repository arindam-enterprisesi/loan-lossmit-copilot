# ruff: noqa: I001
"""The scenario files reproduce every figure in the Feature Design worked examples.

Expected values are typed in from the Feature Design (section numbers in each test),
and every other figure is recomputed from the scenario with Decimal. Nothing is rendered here.
"""

from __future__ import annotations

from datetime import date, timedelta
from statistics import median

import pytest

from tests.data.helpers import D, fmt, pct, q
from synthetic.schema import (
    BankStatementDoc,
    Scenario,
    load_scenario,
    running_balances,
    scenario_names,
    statement_pages,
)


def facts(scenario: Scenario, doc_id: str):
    return scenario.document(doc_id).facts


# ------------------------------------------------------------------ the files themselves


def test_both_scenarios_exist_and_load() -> None:
    assert scenario_names() == ["angela_whitfield", "daniel_reyes"]
    for name in scenario_names():
        scenario = load_scenario(name)
        assert scenario.label == "illustrative"
        assert scenario.version


def test_scenario_files_hold_no_floats_and_money_has_cents(tmp_path) -> None:
    bad = tmp_path / "bad.json"
    bad.write_text('{"scenario_id": "x", "amount": 1.5}', encoding="utf-8")
    with pytest.raises(ValueError, match="floats are not allowed"):
        load_scenario(bad)


def test_provenance_separates_documented_derived_and_invented(
    daniel: Scenario, angela: Scenario
) -> None:
    for scenario in (daniel, angela):
        assert set(scenario.provenance) == {"documented", "derived", "invented"}
        assert scenario.provenance["documented"] and scenario.provenance["derived"]


# ------------------------------------------------------------------ Daniel Reyes


def test_pay_stub_figures_feature_design_1_8(daniel: Scenario) -> None:
    f = facts(daniel, "pay_stub_2026-09-27")
    assert (f.period_start, f.period_end) == (date(2026, 9, 14), date(2026, 9, 27))
    assert (f.gross_current, f.deductions_current, f.net_current) == (
        D("3070.50"),
        D("1036.89"),
        D("2033.61"),
    )
    assert f.gross_current - f.deductions_current == f.net_current
    assert f.printed_net_current == D("2083.61")  # the documented defect
    assert sum(e.current for e in f.earnings) == f.gross_current
    assert sum(e.ytd for e in f.earnings) == f.gross_ytd
    assert sum(d.current for d in f.deductions) == f.deductions_current
    assert sum(d.ytd for d in f.deductions) == f.deductions_ytd
    assert f.gross_ytd - f.deductions_ytd == f.net_ytd


def test_income_methods_feature_design_2_3_and_2_8(daniel: Scenario) -> None:
    f = facts(daniel, "pay_stub_2026-09-27")
    regular, overtime, bonus = f.earnings
    rate, hours = regular.rate, regular.hours
    assert rate is not None and hours is not None
    n, per_year = f.period_number, f.periods_per_year
    # base pay, hourly: rate x regular hours x periods per year / 12
    assert q(rate * hours * per_year / 12) == D("5980.00")
    # year-to-date average: YTD x periods per year / (periods elapsed x 12)
    raw_ot = overtime.ytd * per_year / (n * 12)
    monthly_ot = q(raw_ot)
    monthly_bonus = q(bonus.ytd * per_year / (n * 12))
    assert (monthly_ot, monthly_bonus) == (D("444.41"), D("228.34"))
    # not a half-cent tie, which half-even rounding would resolve the other way
    assert abs(raw_ot - monthly_ot) != D("0.005")
    assert q(regular.ytd * per_year / (n * 12)) == D("5980.00")
    assert D("5980.00") + monthly_ot == D("6424.41")
    annualized = (D("5980.00") + monthly_ot + monthly_bonus) * 12
    assert annualized == D("79833.00") == f.gross_current * per_year
    assert f.gross_ytd / n == f.gross_current  # YTD average equals the current period: no flag


def test_w2_trend_and_deferrals_feature_design_2_8(daniel: Scenario) -> None:
    w24, w25 = facts(daniel, "w2_2024"), facts(daniel, "w2_2025")
    assert (w24.box5, w25.box5) == (D("70431.80"), D("74298.60"))
    assert pct(w25.box5 - w24.box5, w24.box5) == D("5.49")
    assert pct(D("79833.00") - w25.box5, w25.box5) == D("7.45")
    for w2 in (w24, w25):
        deferral = next(b.amount for b in w2.box12 if b.code == "D")
        assert w2.box5 - w2.box1 == deferral  # the gap the AI explains from Box 12
        assert deferral == q(w2.box5 * D("0.06"))
    f1040_24, f1040_25 = facts(daniel, "form_1040_2024"), facts(daniel, "form_1040_2025")
    assert f1040_24.wages == w24.box1 and f1040_25.wages == w25.box1
    for form in (f1040_24, f1040_25):
        assert form.wages + form.taxable_interest == form.total_income
        assert form.total_income - form.adjustments == form.adjusted_gross_income


def test_assets_liabilities_ratios_feature_design_3_8(daniel: Scenario) -> None:
    loan = daniel.loan_scenario
    assert loan is not None
    report = facts(daniel, "credit_report_2026-10-12")
    obligations = sum(t.monthly_payment for t in report.tradelines if t.monthly_payment > 0)
    assert obligations == D("693.00")
    september = facts(daniel, "bank_statement_2026-09")
    assets = september.closing_balance
    assert assets == D("9226.32")
    assert loan.funds_needed_to_close == D("36500.00")
    assert loan.funds_needed_to_close - assets == D("27273.68")
    base, with_overtime = D("5980.00"), D("6424.41")
    housing = loan.proposed_housing_payment
    assert pct(housing, base) == D("33.11")
    assert pct(housing + obligations, base) == D("44.70")
    assert pct(housing + obligations, with_overtime) == D("41.61")
    assert pct(loan.loan_amount, loan.property_value) == D("90.00")


def test_credit_metrics_feature_design_4_8(daniel: Scenario) -> None:
    report = facts(daniel, "credit_report_2026-10-12")
    assert report.report_date == date(2026, 10, 12)
    scores = [s.score for s in report.scores]
    assert sorted(scores) == [698, 705, 712] and median(scores) == 705  # middle of three
    by_name = {t.creditor: t for t in report.tradelines}
    northgate = by_name["Northgate Card"]
    assert northgate.credit_limit is not None
    assert pct(northgate.balance, northgate.credit_limit) == D("36.75")
    revolving = [t for t in report.tradelines if t.account_type == "revolving"]
    balances = sum(t.balance for t in revolving)
    limits = sum(t.credit_limit for t in revolving if t.credit_limit is not None)
    assert pct(balances, limits) == D("28.00")
    # one 30-day late payment, 19 months before the report date
    late = [t for t in report.tradelines if t.late_30 or t.late_60 or t.late_90]
    assert [t.creditor for t in late] == ["Northgate Card"]
    assert (northgate.late_30, northgate.late_60, northgate.late_90) == (1, 0, 0)
    last = northgate.most_recent_late
    assert last is not None
    months = (report.report_date.year - last.year) * 12 + report.report_date.month - last.month
    months -= 1 if report.report_date.day < last.day else 0
    assert months == 19
    # inquiries: Harbor Retail matches the card opened that day; Orion Mortgage matches nothing
    harbor_card = by_name["Harbor Retail Card"]
    inquiries = {i.creditor: i.date for i in report.inquiries}
    assert harbor_card.open_date == inquiries["Harbor Retail"]
    orion = inquiries["Orion Mortgage"]
    assert report.report_date - orion <= timedelta(days=120)  # inside the inquiry window
    assert all(abs((t.open_date - orion).days) > 30 for t in report.tradelines)


def test_bank_statements_reconcile_and_chain(daniel: Scenario, angela: Scenario) -> None:
    for scenario in (daniel, angela):
        for doc in scenario.documents:
            if not isinstance(doc, BankStatementDoc):
                continue
            f = doc.facts
            assert f.opening_balance + sum(t.amount for t in f.transactions) == f.closing_balance
            assert running_balances(f)[-1] == f.closing_balance
            assert len(statement_pages(f)) == f.total_pages_printed
            assert all(f.period_start <= t.date <= f.period_end for t in f.transactions)
    aug, sep = facts(daniel, "bank_statement_2026-08"), facts(daniel, "bank_statement_2026-09")
    assert aug.closing_balance == sep.opening_balance


def test_payroll_deposits_and_the_large_deposit_feature_design_3_3(daniel: Scenario) -> None:
    stub = facts(daniel, "pay_stub_2026-09-27")
    pay_dates = {stub.pay_date + timedelta(days=14 * k) for k in range(-6, 3)}
    payroll: list[tuple[date, object]] = []
    large = []
    for month in ("bank_statement_2026-08", "bank_statement_2026-09"):
        for t in facts(daniel, month).transactions:
            if t.category == "payroll deposit":
                payroll.append((t.date, t.amount))
                # employer in the description, amount within 1.00, date within 3 days of a pay date
                assert "CEDAR VALLEY" in t.description
                assert abs(t.amount - stub.net_current) <= D("1.00")
                assert any(abs((t.date - p).days) <= 3 for p in pay_dates)
            elif t.amount >= D("1000.00") and t.category != "transfer between own accounts":
                large.append(t)
    assert len(payroll) == 4
    september = [d for d, _ in payroll if d.month == 9]
    assert len(september) == 2  # "both September paychecks"
    assert [(t.date, t.amount, t.counterparty) for t in large] == [
        (date(2026, 9, 22), D("2000.00"), "Patricia Owens")
    ]


def test_recurring_debits_match_the_credit_report(daniel: Scenario) -> None:
    aug, sep = facts(daniel, "bank_statement_2026-08"), facts(daniel, "bank_statement_2026-09")
    report = facts(daniel, "credit_report_2026-10-12")
    payments = {t.creditor: t.monthly_payment for t in report.tradelines}

    def debits(statement) -> dict[str, object]:
        return {t.counterparty: -t.amount for t in statement.transactions if t.amount < 0}

    recurring = {p for p in debits(aug) if p in debits(sep)}
    for creditor in ("Northgate Card", "Cardinal Rewards Visa", "Lakeshore Auto Finance"):
        assert creditor in recurring and debits(sep)[creditor] == payments[creditor]
    assert debits(sep)["Brightpath Student Loan Servicing"] == D("110.00")
    # the new Harbor Retail card has no payment history in the bank statements yet
    assert "Harbor Retail Card" not in debits(sep)


def test_completeness_inputs_feature_design_6_8_and_fsd_11(daniel: Scenario) -> None:
    stub = facts(daniel, "pay_stub_2026-09-27")
    covered = (stub.period_end - stub.period_start).days + 1
    assert (covered, 30 - covered) == (14, 16)
    case = [d.id for d in daniel.documents if d.role == "case"]
    withheld = [d.id for d in daniel.documents if d.role == "withheld"]
    assert len(case) == 7 and sorted(withheld) == ["form_1040_2024", "w2_2024"]
    assert not any("2024" in doc_id and "statement" not in doc_id for doc_id in case)
    september = daniel.document("bank_statement_2026-09")
    assert september.declared_type == "tax_return_1040" and september.type == "bank_statement"
    august = facts(daniel, "bank_statement_2026-08")
    assert (august.total_pages_printed, august.pages_rendered) == (3, 2)
    third = statement_pages(august)[2]
    visible = sum(t.amount for page in statement_pages(august)[:2] for t in page)
    assert august.opening_balance + visible + sum(t.amount for t in third) == august.closing_balance


def test_expected_block_matches_the_documented_results(daniel: Scenario) -> None:
    e = daniel.expected
    assert e["income"]["base_monthly"] == "5980.00"
    assert e["income"]["overtime_monthly"] == "444.41"
    assert e["income"]["bonus_monthly"] == "228.34"
    assert e["income"]["candidate_monthly_with_overtime"] == "6424.41"
    assert e["income"]["annualized_2026"] == "79833.00"
    al = e["assets_liabilities"]
    assert (al["documented_assets"], al["shortfall"], al["obligations_monthly"]) == (
        "9226.32",
        "27273.68",
        "693.00",
    )
    assert (
        al["front_end_ratio_pct"],
        al["dti_pct"],
        al["dti_with_overtime_pct"],
        al["ltv_pct"],
    ) == (
        "33.11",
        "44.70",
        "41.61",
        "90.00",
    )
    assert e["credit"]["representative_score"] == 705
    assert e["completeness"]["pay_stub_days_short"] == 16
    assert e["completeness"]["overall"] == "incomplete"


# ------------------------------------------------------------------ Angela Whitfield


def test_pay_stubs_feature_design_7_8(angela: Scenario) -> None:
    before, after = facts(angela, "pay_stub_2026-06-30"), facts(angela, "pay_stub_2026-09-30")
    assert (before.gross_current, after.gross_current) == (D("2800.00"), D("2100.00"))
    assert pct(before.gross_current - after.gross_current, before.gross_current) == D("25.00")
    for stub, hours in ((before, D("80.00")), (after, D("60.00"))):
        earning = stub.earnings[0]
        assert earning.rate == D("35.00") and earning.hours == hours
        assert earning.rate * earning.hours == stub.gross_current
        assert stub.gross_current - stub.deductions_current == stub.net_current
        assert sum(d.current for d in stub.deductions) == stub.deductions_current
    assert after.gross_current * 2 == D("4200.00")  # monthly income, semi-monthly pay
    assert after.net_current * 2 == D("3350.00")  # monthly net


def test_budget_and_measures_feature_design_7_8(angela: Scenario) -> None:
    application = facts(angela, "mortgage_assistance_application")
    stated = {e.category: e.amount for e in application.expenses}
    assert sum(stated.values()) == application.total_expenses == D("3420.00")
    expected_observed = angela.expected["budget"]["observed"]
    observed = {k: D(v) for k, v in expected_observed.items()}
    assert sum(observed.values()) == D("3630.00")
    differing = {k for k in stated if stated[k] != observed[k]}
    assert differing == {"Other"} and (stated["Other"], observed["Other"]) == (
        D("200.00"),
        D("410.00"),
    )
    # stated against observed: a difference above 10% or 25.00, whichever is larger, is flagged
    assert observed["Other"] - stated["Other"] > max(stated["Other"] * D("0.10"), D("25.00"))

    net = D("3350.00")
    assert net - sum(stated.values()) == D("-70.00")
    assert net - sum(observed.values()) == D("-280.00")

    payment, before_income, after_income = D("1720.00"), D("5600.00"), D("4200.00")
    assert pct(payment, after_income) == D("40.95") and pct(payment, before_income) == D("30.71")
    statement = facts(angela, "mortgage_statement_2026-10")
    assert (
        statement.monthly_payment == payment == statement.principal_and_interest + statement.escrow
    )
    arrears = statement.past_due_amount
    assert arrears == statement.total_due == payment * 3 == D("5160.00")
    assert len(statement.payments_past_due) == 3
    liquid = facts(angela, "bank_statement_2026-09").closing_balance
    assert liquid == D("640.25") and pct(liquid, arrears) == D("12.41")


def test_observed_spending_comes_from_the_bank_statements(angela: Scenario) -> None:
    july, september = (
        facts(angela, "bank_statement_2026-07"),
        facts(angela, "bank_statement_2026-09"),
    )
    expected = {
        "housing payment": D("1720.00"),
        "utility": D("310.00"),
        "everyday spending": D("780.00"),
        "loan payment": D("410.00"),
        "other": D("410.00"),
    }

    def totals(statement) -> dict[str, object]:
        out: dict[str, D] = {}
        for t in statement.transactions:
            if t.amount < 0 and t.category != "transfer out":
                out[t.category] = out.get(t.category, D("0")) - t.amount
        return out

    # July: the mortgage was still being paid, so every observed category is there (3,630.00)
    assert totals(july) == expected
    assert sum(totals(july).values()) == D("3630.00")
    # September: same non-housing spending, and no mortgage payment (she is behind)
    assert totals(september) == {k: v for k, v in expected.items() if k != "housing payment"}
    income = sum(t.amount for t in july.transactions if t.category == "payroll deposit")
    assert income == D("3350.00") and july.opening_balance - july.closing_balance == D("280.00")


def test_lender_view_feature_design_8_3_and_8_8(angela: Scenario) -> None:
    record = angela.loan_record
    assert record is not None
    assert record.unpaid_principal_balance == D("212400.00")
    claim = record.unpaid_principal_balance + record.past_due_amount
    value, discount, costs = D("265000.00"), D("0.15"), D("24000.00")
    recovery = value * (1 - discount) - costs
    loss = claim - recovery
    assert (claim, recovery, loss) == (D("217560.00"), D("201250.00"), D("16310.00"))
    target = D("4200.00") * D("0.35")
    reduction = record.monthly_payment - target
    assert (target, reduction) == (D("1470.00"), D("250.00"))
    over_horizon = reduction * 36
    expected_loss = loss * D("0.30")
    assert (over_horizon, expected_loss) == (D("9000.00"), D("4893.00"))
    assert over_horizon + expected_loss == D("13893.00")
    assert loss - (over_horizon + expected_loss) == D("2417.00")
    lender = angela.expected["lender_view"]
    assert (
        lender["modification_advantage"] == "2417.00"
        and lender["foreclosure"]["loss"] == "16310.00"
    )


def test_loan_record_matches_the_mortgage_statement(angela: Scenario) -> None:
    record, statement = angela.loan_record, facts(angela, "mortgage_statement_2026-10")
    assert record is not None
    assert record.loan_id == statement.loan_number
    assert record.unpaid_principal_balance == statement.unpaid_principal_balance
    assert (record.past_due_amount, record.total_due) == (
        statement.past_due_amount,
        statement.total_due,
    )
    assert record.monthly_payment == statement.monthly_payment
    assert record.missed_payment_due_dates == statement.payments_past_due
    assert record.investor == "Sample Investor A"


def test_hardship_letter_quotes_feature_design_7_5(angela: Scenario) -> None:
    letter = facts(angela, "hardship_letter")
    reason, intent = letter.quotes["primary_reason"], letter.quotes["intent"]
    assert (reason.line, intent.line) == (6, 14)  # p1-L6 and p1-L14
    assert reason.quote == "cut my hours from 40 to 30 a week in July"
    assert intent.quote == "I want to keep my home"
    assert reason.quote in letter.lines[reason.line - 1]
    assert intent.quote in letter.lines[intent.line - 1]
    assert "5,160.00" in " ".join(
        letter.lines
    )  # a stated amount the code compares with the statement


def test_angela_has_no_august_bank_statement(angela: Scenario) -> None:
    months = sorted(
        d.facts.period_start.month for d in angela.documents if isinstance(d, BankStatementDoc)
    )
    assert months == [7, 9]
    assert angela.expected["completeness"]["missing"] == ["bank_statement_2026-08"]
    assert all(d.role == "case" for d in angela.documents) and len(angela.documents) == 8


def test_cross_document_figures_are_identical(daniel: Scenario, angela: Scenario) -> None:
    # 2,033.61 is Daniel's true net pay everywhere it matters
    stub = facts(daniel, "pay_stub_2026-09-27")
    deposits = {
        t.amount
        for m in ("bank_statement_2026-08", "bank_statement_2026-09")
        for t in facts(daniel, m).transactions
        if t.category == "payroll deposit"
    }
    assert deposits == {stub.net_current} == {D("2033.61")}
    # Angela: net 1,675.00 and the 1,720.00 payment agree across stub, bank statements, application
    net = facts(angela, "pay_stub_2026-09-30").net_current
    assert (
        {
            t.amount
            for t in facts(angela, "bank_statement_2026-09").transactions
            if t.category == "payroll deposit"
        }
        == {net}
        == {D("1675.00")}
    )
    july_payment = [
        -t.amount
        for t in facts(angela, "bank_statement_2026-07").transactions
        if t.category == "housing payment"
    ]
    application = facts(angela, "mortgage_assistance_application")
    housing = next(e.amount for e in application.expenses if e.category.startswith("Housing"))
    assert july_payment == [housing] == [D("1720.00")]
    assert fmt(housing) == "1,720.00"

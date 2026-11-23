"""Golden: Daniel Reyes's sample credit report (Feature Design 4.8).

The expected figures come from the scenario's ``expected`` block and the Feature Design literals:
representative score 705, Northgate Card utilization 36.75% (above the 30% review level), total
revolving utilization 28.00%, one 30-day late payment 19 months before the report date, monthly
payments of 693.00, a new Harbor Retail card opened the day of an inquiry, and an Orion Mortgage
inquiry with no matching account.
"""

from __future__ import annotations

import json
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

from app.services.analysis_config import get_analysis_config
from app.services.credit import (
    CreditInputs,
    CreditOutcome,
    InquiryIn,
    ScoreIn,
    TradelineIn,
    analyze,
    months_between,
)

D = Decimal
SCENARIO = Path(__file__).resolve().parents[3] / "data" / "synthetic" / "scenarios"
DATA: dict[str, Any] = json.loads((SCENARIO / "daniel_reyes.json").read_text("utf-8"))
REPORT: dict[str, Any] = next(d for d in DATA["documents"] if d["type"] == "credit_report")["facts"]
EXPECTED: dict[str, Any] = DATA["expected"]["credit"]
CFG = get_analysis_config()


def day(text: str | None) -> date | None:
    return date.fromisoformat(text) if text else None


def amount(text: str | None) -> Decimal | None:
    return D(text) if text is not None else None


def report_inputs(**changes: Any) -> CreditInputs:
    scores = tuple(
        ScoreIn(s["bureau"], s["score"], (f"p1-L{3 + n}",)) for n, s in enumerate(REPORT["scores"])
    )
    lines = tuple(
        TradelineIn(
            number=n,
            creditor=t["creditor"],
            account_type=t["account_type"],
            ownership=t["ownership"],
            opened_on=day(t["open_date"]),
            status=t["status"],
            balance=amount(t["balance"]),
            credit_limit=amount(t["credit_limit"]),
            monthly_payment=amount(t["monthly_payment"]),
            past_due=amount(t["past_due"]),
            late_30=t["late_30"],
            late_60=t["late_60"],
            late_90=t["late_90"],
            last_late_on=day(t["most_recent_late"]),
            remarks=t["remarks"],
            lines=(f"p2-L{10 + n}",),
        )
        for n, t in enumerate(REPORT["tradelines"], start=1)
    )
    inquiries = tuple(
        InquiryIn(n, q["creditor"], day(q["date"]), (f"p3-L{4 + n}",))
        for n, q in enumerate(REPORT["inquiries"], start=1)
    )
    base: dict[str, Any] = {
        "report_date": day(REPORT["report_date"]),
        "scores": scores,
        "tradelines": lines,
        "inquiries": inquiries,
    }
    return CreditInputs(**{**base, **changes})


def calc(outcome: CreditOutcome, name: str) -> Any:
    return next(c for c in outcome.calcs if c.name == name)


def codes(outcome: CreditOutcome) -> list[str]:
    return [f.code for f in outcome.flags]


def test_the_representative_score_is_the_middle_of_three() -> None:
    outcome = analyze(report_inputs(), CFG)

    assert outcome.representative is not None
    assert outcome.representative.value == D(EXPECTED["representative_score"]) == D(705)
    assert outcome.representative.working == "Scores 712, 698, 705: the middle of the scores is 705"
    assert outcome.representative_bureau == "Bureau C"
    assert outcome.method == "middle_of_three_lower_of_two"


def test_the_lower_of_two_and_a_single_score() -> None:
    two = analyze(report_inputs(scores=(ScoreIn("A", 712), ScoreIn("B", 698))), CFG)
    one = analyze(report_inputs(scores=(ScoreIn("A", 712),)), CFG)

    assert two.representative is not None and two.representative.value == D(698)
    assert "lower of two" in two.representative.working
    assert one.representative is not None and one.representative.value == D(712)


def test_northgate_utilization_is_36_75_percent_and_above_the_review_level() -> None:
    outcome = analyze(report_inputs(), CFG)

    northgate = calc(outcome, "utilization_northgate_card")
    assert northgate.value == D("0.367500")
    assert northgate.working == "2,940.00 / 8,000.00 = 36.75%"
    assert str(northgate.value * 100) == EXPECTED["northgate_utilization_pct"] + "0000"
    over = [r.tradeline.creditor for r in outcome.tradelines if r.utilization_over_review_level]
    assert over == ["Northgate Card"]  # Cardinal is 20.67% and Harbor 15.00%


def test_total_revolving_utilization_is_28_percent() -> None:
    total = calc(analyze(report_inputs(), CFG), "total_revolving_utilization")

    assert total.value == D("0.280000")
    assert total.working == "4,480.00 / 16,000.00 = 28.00%"
    assert total.inputs == {"balances": "4480.00", "limits": "16000.00"}


def test_installment_accounts_have_no_utilization() -> None:
    names = {c.name for c in analyze(report_inputs(), CFG).calcs}

    assert not any("lakeshore" in n and n.startswith("utilization") for n in names)
    assert not any("brightpath" in n and n.startswith("utilization") for n in names)


def test_one_30_day_late_payment_19_months_before_the_report() -> None:
    outcome = analyze(report_inputs(), CFG)

    months = calc(outcome, "months_since_last_late_northgate_card")
    late = EXPECTED["late_payments"][0]
    assert months.value == D(late["months_before_report"]) == D(19)
    assert months.working == "2025-03-05 to 2026-10-12 = 19 months"
    assert outcome.summary[0] == (
        "One 30-day late payment on Northgate Card, 19 months before the report date."
    )
    assert [r.tradeline.creditor for r in outcome.tradelines if r.late_in_lookback] == [
        "Northgate Card"
    ]


def test_a_late_payment_older_than_the_lookback_is_shown_but_not_flagged() -> None:
    old = report_inputs()
    lines = tuple(
        t
        if t.creditor != "Northgate Card"
        else TradelineIn(**{**t.__dict__, "last_late_on": date(2024, 1, 5)})
        for t in old.tradelines
    )

    outcome = analyze(report_inputs(tradelines=lines), CFG)

    assert calc(outcome, "months_since_last_late_northgate_card").value == D(33)
    assert "CR-W102" not in codes(outcome)
    assert outcome.summary[0] == "No late payments within the lookback."


def test_monthly_payments_total_693_by_account_type() -> None:
    outcome = analyze(report_inputs(), CFG)

    assert calc(outcome, "monthly_payments_total").value == D(EXPECTED["monthly_payments_total"])
    assert calc(outcome, "monthly_payments_total").working == (
        "88.00 + 40.00 + 35.00 + 420.00 + 110.00 = 693.00"
    )
    assert calc(outcome, "monthly_payments_revolving").value == D("163.00")
    assert calc(outcome, "monthly_payments_installment").value == D("530.00")


def test_the_new_harbor_card_matches_its_inquiry_and_orion_has_no_account() -> None:
    outcome = analyze(report_inputs(), CFG)

    matches = {
        r.inquiry.creditor: r.matched.creditor if r.matched else None for r in outcome.inquiries
    }
    assert (
        matches
        == {e["creditor"]: e["matched_account"] for e in EXPECTED["inquiries"]}
        == {"Harbor Retail": "Harbor Retail Card", "Orion Mortgage": None}
    )
    assert "CR-W103" in codes(outcome) and "CR-I102" in codes(outcome)
    orion = next(f for f in outcome.flags if f.code == "CR-W103")
    assert "Orion Mortgage" in orion.message and orion.evidence[0]["field"] == "inquiry_002"


def test_an_inquiry_outside_the_window_is_listed_but_not_flagged() -> None:
    inquiries = (InquiryIn(1, "Orion Mortgage", date(2026, 1, 8), ("p3-L5",)),)

    outcome = analyze(report_inputs(inquiries=inquiries), CFG)

    assert outcome.inquiries[0].in_window is False
    assert "CR-W103" not in codes(outcome)


def test_the_flags_for_daniels_report() -> None:
    outcome = analyze(report_inputs(), CFG)

    assert sorted(codes(outcome)) == ["CR-I102", "CR-W101", "CR-W102", "CR-W103"]
    assert all(f.evidence and f.evidence[0]["line_ids"] for f in outcome.flags)
    assert all(f.severity in ("warning", "info") for f in outcome.flags)


def test_alerts_are_flagged_and_come_first_in_the_summary() -> None:
    outcome = analyze(report_inputs(alerts=("Fraud alert on file",), alert_lines=("p1-L2",)), CFG)

    assert "CR-W105" in codes(outcome)
    assert outcome.summary[0] == "Alerts on the report: Fraud alert on file."


def test_a_past_due_balance_makes_the_account_derogatory() -> None:
    lines = tuple(
        t
        if t.creditor != "Lakeshore Auto Finance"
        else TradelineIn(**{**t.__dict__, "past_due": D("420.00")})
        for t in report_inputs().tradelines
    )

    outcome = analyze(report_inputs(tradelines=lines), CFG)

    assert [t.creditor for t in outcome.derogatory] == ["Lakeshore Auto Finance"]
    assert "CR-W104" in codes(outcome)


def test_every_calculation_carries_working_and_the_lines_it_came_from() -> None:
    outcome = analyze(report_inputs(), CFG)

    assert all(c.working and c.config_version.startswith("thresholds@") for c in outcome.calcs)
    for name in ("utilization_northgate_card", "monthly_payments_total", "representative_score"):
        assert calc(outcome, name).evidence


def test_a_missing_report_says_what_it_cannot_compute() -> None:
    outcome = analyze(CreditInputs(), CFG)

    assert outcome.representative is None and outcome.calcs == []
    assert codes(outcome) == ["CR-I101"]
    assert outcome.notes[0].startswith("Cannot compute the credit analysis")


def test_months_between_counts_whole_months() -> None:
    assert months_between(date(2025, 3, 5), date(2026, 10, 12)) == 19
    assert months_between(date(2025, 3, 20), date(2026, 10, 12)) == 18
    assert months_between(date(2026, 10, 12), date(2026, 10, 12)) == 0


def test_the_same_report_gives_the_same_result() -> None:
    assert analyze(report_inputs(), CFG) == analyze(report_inputs(), CFG)


def test_no_text_says_approve_deny_offer_eligible_or_qualifies() -> None:
    outcome = analyze(report_inputs(), CFG)
    text = json.dumps(
        [outcome.summary, [f.message for f in outcome.flags], [c.working for c in outcome.calcs]]
    ).lower()

    for word in ("approve", "deny", "denied", "offer", "eligible", "qualif"):
        assert word not in text

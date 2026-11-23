"""Golden: Angela Whitfield under Sample Investor A (Feature Design 8.3 and 8.8).

The expected figures come from the scenario's ``expected`` block and the Feature Design literals, so
a drift in the engine, the rule set or the scenario shows up here. The inputs are the confirmed
hardship profile (duration unknown, intent keep) and the figures the documents carry.
"""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from app.services.rules_config import RULE_SETS_DIR as SOURCE_DIR
from app.services.rules_config import load_rule_set
from app.services.rules_engine import Fact, Judgement, RuleInputs, RulesOutcome, evaluate

D = Decimal
SCENARIO = Path(__file__).resolve().parents[3] / "data" / "synthetic" / "scenarios"
EXPECTED: dict[str, Any] = json.loads((SCENARIO / "angela_whitfield.json").read_text("utf-8"))
LOAN = EXPECTED["loan_record"]
LENDER = EXPECTED["expected"]["lender_view"]
BUDGET = EXPECTED["expected"]["budget"]
RULES = load_rule_set().config


def inputs(**changes: Any) -> RuleInputs:
    base: dict[str, Any] = {
        "duration": Judgement("unknown", True),
        "intent": Judgement("keep", True),
        "surplus": Fact(-D(BUDGET["deficit_stated"])),
        "arrears": Fact(D(LOAN["past_due_amount"])),
        "contractual_payment": Fact(D(LOAN["monthly_payment"])),
        "gross_monthly_income": Fact(D(EXPECTED["expected"]["income"]["gross_monthly"])),
        "unpaid_balance": Fact(D(LOAN["unpaid_principal_balance"])),
        "months_delinquent": Fact(D(LOAN["months_delinquent"])),
    }
    return RuleInputs(**{**base, **changes})


def statuses(outcome: RulesOutcome) -> dict[str, str]:
    return {o.option: o.status for o in outcome.options}


def figure(outcome: RulesOutcome, name: str) -> Any:
    return next(c for c in outcome.calcs if c.name == name)


def condition(outcome: RulesOutcome, condition_id: str) -> dict[str, Any]:
    return next(c for o in outcome.options for c in o.conditions if c["id"] == condition_id)


def test_the_waterfall_matches_the_worked_example() -> None:
    outcome = evaluate(RULES, inputs())
    assert statuses(outcome) == {
        "repayment_plan": "not_met",
        "forbearance": "not_met",
        "payment_deferral": "not_met",
        "loan_modification": EXPECTED["expected"]["waterfall"]["loan_modification"],
        "short_sale": "not_reached",
        "deed_in_lieu": "not_reached",
    }
    assert [o.order_no for o in outcome.options] == [1, 2, 3, 4, 5, 6]


def test_repayment_plan_is_not_met_because_the_surplus_is_below_arrears_over_six() -> None:
    surplus = condition(evaluate(RULES, inputs()), "repayment_plan.surplus")
    assert surplus["status"] == "not_met"
    assert surplus["values"] == {"surplus": "-70.00", "arrears": "5160.00", "needed": "860.00"}


def test_deferral_is_not_met_but_three_months_delinquent_is_within_the_limit() -> None:
    outcome = evaluate(RULES, inputs())
    assert condition(outcome, "payment_deferral.surplus")["status"] == "not_met"
    delinquent = condition(outcome, "payment_deferral.months_delinquent")
    assert delinquent["status"] == "met"
    assert delinquent["values"] == {"months_delinquent": "3", "limit": "6"}


def test_the_target_payment_is_35_percent_of_documented_gross_income() -> None:
    outcome = evaluate(RULES, inputs())
    target = figure(outcome, "target_payment")
    assert target.value == D(LENDER["target_payment"]) == D("1470.00")
    assert target.working == "35% x 4,200.00 = 1,470.00"
    modification = condition(outcome, "loan_modification.target_payment")
    assert modification["status"] == "met"
    assert modification["values"]["target_payment"] == "1470.00"
    assert modification["values"]["contractual_payment"] == "1720.00"


def test_the_lender_view_matches_the_feature_design_to_the_cent() -> None:
    outcome = evaluate(RULES, inputs())
    got = {c.name: c.value for c in outcome.calcs}
    assert got["foreclosure_claim"] == D(LENDER["foreclosure"]["claim"]) == D("217560.00")
    assert got["foreclosure_net_recovery"] == D(LENDER["foreclosure"]["net_recovery"])
    assert got["foreclosure_loss"] == D(LENDER["foreclosure"]["loss"]) == D("16310.00")
    assert got["modification_payment_reduction_monthly"] == D("250.00")
    assert got["modification_payment_reduction_total"] == D("9000.00")
    assert got["modification_expected_redefault_loss"] == D("4893.00")
    assert got["modification_cost"] == D(LENDER["modification"]["expected_cost"]) == D("13893.00")
    assert got["modification_advantage"] == D(LENDER["modification_advantage"]) == D("2417.00")
    assert outcome.lender_settings == LENDER["settings"]


def test_every_lender_figure_shows_its_working() -> None:
    outcome = evaluate(RULES, inputs())
    assert figure(outcome, "foreclosure_claim").working == "212,400.00 + 5,160.00 = 217,560.00"
    assert figure(outcome, "foreclosure_net_recovery").working == (
        "265,000.00 - 15% (39,750.00) - 24,000.00 = 201,250.00"
    )
    assert figure(outcome, "foreclosure_loss").working == "217,560.00 - 201,250.00 = 16,310.00"
    assert figure(outcome, "modification_payment_reduction_total").working == (
        "250.00 x 36 = 9,000.00"
    )
    assert figure(outcome, "modification_cost").working == "9,000.00 + 4,893.00 = 13,893.00"
    assert figure(outcome, "modification_advantage").working == "16,310.00 - 13,893.00 = 2,417.00"
    assert len(outcome.lender_figures) == 9
    assert all(
        figure(outcome, name).config_version == "rule_set@1" for name in outcome.lender_figures
    )


def test_unconfirmed_judgements_need_confirmation_and_are_not_used() -> None:
    outcome = evaluate(
        RULES, inputs(duration=Judgement("unknown", False), intent=Judgement("keep", False))
    )
    assert statuses(outcome)["loan_modification"] == "needs_confirmation"
    assert statuses(outcome)["forbearance"] == "needs_confirmation"
    # Options already failing on a figure stay not met: the figure does not need a judgement.
    assert statuses(outcome)["repayment_plan"] == "not_met"
    hardship = condition(outcome, "loan_modification.hardship_long_term")
    assert hardship["status"] == "needs_confirmation"
    assert hardship["values"] == {"duration": "unknown", "confirmed": "no"}
    # Nobody can yet say that no earlier option is met, so the later options wait too.
    assert statuses(outcome)["short_sale"] == "needs_confirmation"
    assert condition(outcome, "short_sale.reached")["status"] == "needs_confirmation"


def test_a_letter_not_read_leaves_the_judgements_not_evaluable() -> None:
    outcome = evaluate(
        RULES, inputs(duration=Judgement(None, False), intent=Judgement(None, False))
    )
    assert condition(outcome, "forbearance.hardship_temporary")["status"] == "not_evaluable"
    assert statuses(outcome)["loan_modification"] == "not_evaluable"


def test_a_missing_figure_makes_its_condition_not_evaluable_and_says_what() -> None:
    outcome = evaluate(RULES, inputs(surplus=None, months_delinquent=None, arrears=None))
    surplus = condition(outcome, "repayment_plan.surplus")
    assert surplus["status"] == "not_evaluable" and "surplus" in surplus["note"]
    assert condition(outcome, "payment_deferral.months_delinquent")["status"] == "not_evaluable"
    assert outcome.lender_figures == []  # no claim without arrears


def test_no_income_means_no_target_payment_and_no_lender_view() -> None:
    outcome = evaluate(RULES, inputs(gross_monthly_income=None))
    assert statuses(outcome)["loan_modification"] == "not_evaluable"
    assert not any(c.name == "target_payment" for c in outcome.calcs)
    assert outcome.lender_figures == []


def test_a_target_payment_at_or_above_the_payment_is_not_met() -> None:
    outcome = evaluate(RULES, inputs(gross_monthly_income=Fact(D("5000.00"))))
    assert condition(outcome, "loan_modification.target_payment")["status"] == "not_met"
    assert statuses(outcome)["loan_modification"] == "not_met"
    assert statuses(outcome)["short_sale"] == "not_evaluable"  # the sample defines no conditions
    # The reduction is never negative: 0.35 x 5,000.00 = 1,750.00 is above 1,720.00.
    assert figure(outcome, "modification_payment_reduction_monthly").value == D("0.00")


def test_the_waterfall_stops_at_the_first_option_whose_conditions_are_met() -> None:
    # A surplus of 900.00 meets the repayment plan's surplus; only the missing "resolved" value
    # stands in the way, and a reviewer can supply it by override. Without it the plan is not met.
    outcome = evaluate(RULES, inputs(surplus=Fact(D("900.00"))))
    assert condition(outcome, "repayment_plan.surplus")["status"] == "met"
    assert statuses(outcome)["repayment_plan"] == "not_met"
    note = condition(outcome, "repayment_plan.hardship_resolved")["note"]
    assert "no 'resolved' value" in note


def test_a_changed_setting_changes_the_result_and_nothing_is_hard_coded(tmp_path: Path) -> None:
    source = (SOURCE_DIR / "sample_investor_a_v1.yaml").read_text("utf-8")
    (tmp_path / "variant.yaml").write_text(source.replace('value: "35"', 'value: "30"'), "utf-8")
    variant = load_rule_set("variant", tmp_path).config

    outcome = evaluate(variant, inputs())

    assert figure(outcome, "target_payment").value == D("1260.00")
    assert figure(outcome, "target_payment").working == "30% x 4,200.00 = 1,260.00"
    assert figure(outcome, "modification_payment_reduction_monthly").value == D("460.00")
    assert figure(outcome, "modification_payment_reduction_total").value == D("16560.00")


def test_the_same_inputs_give_the_same_result() -> None:
    first, second = evaluate(RULES, inputs()), evaluate(RULES, inputs())
    assert first == second


def test_every_cited_passage_resolves_in_the_seeded_guide() -> None:
    seeded = json.loads(
        (Path(__file__).resolve().parents[2] / "app/db/demo/guideline_passages.json").read_text(
            "utf-8"
        )
    )
    known = {p["id"] for p in seeded["passages"]}
    cited = {c.passage_id for o in RULES.options for c in o.conditions}
    assert cited <= known, cited - known


@pytest.mark.parametrize("option", [o.option.value for o in RULES.options])
def test_the_result_never_uses_a_decision_word(option: str) -> None:
    outcome = evaluate(RULES, inputs())
    text = json.dumps(
        [o.conditions for o in outcome.options if o.option == option], default=str
    ).lower()
    for word in ("approve", "deny", "denied", "offer", "eligible", "qualif"):
        assert word not in text

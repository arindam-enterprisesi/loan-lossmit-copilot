"""Apply the investor's rule set to a loss mitigation case (Feature Design 8.3, 8.4 and 8.5).

Pure code over plain values: no database, no model, no clock. Every condition is decided here and
every figure is computed here with its working (rules 1 and 2); the agents only read the stored
result. ``met`` means an option's conditions are met and nothing more. It is not an offer or a
decision (rule 3).

A condition is one of a closed set of evaluators named in the rule set file (``rules_config``). Each
returns one of the statuses of ``waterfall_status``:

* ``needs_confirmation``: a judgement (hardship duration, intent to keep the home) was read from the
  letter but a person has not confirmed it, so the rules do not use it (Feature Design 8.2 step 1);
* ``not_evaluable``: something the condition needs is missing (no letter read, no pay stub, no
  mortgage statement), and the condition says what;
* ``met`` or ``not_met`` otherwise.

``waterfall_status.recompute`` then turns the conditions into option statuses, stopping at the first
option whose conditions are all met. The lender view is the comparison with foreclosure, computed
from the rule set's settings (illustrative, labelled, and not any investor's own model).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from app.db.enums import WaterfallStatus
from app.services.calculations import HUNDRED, Calc, Evidence, cents, money, plain
from app.services.rules_config import ConditionSpec, RuleSetConfig
from app.services.waterfall_status import recompute

MET, NOT_MET = WaterfallStatus.MET.value, WaterfallStatus.NOT_MET.value
NEEDS_CONFIRMATION = WaterfallStatus.NEEDS_CONFIRMATION.value
NOT_EVALUABLE = WaterfallStatus.NOT_EVALUABLE.value

NOT_READ = "The hardship letter has not been read for this case."
UNCONFIRMED = "Read from the letter and not yet confirmed by a person, so the rules do not use it."
NO_RESOLVED_VALUE = (
    "The hardship profile records the duration as temporary, long-term or unknown. It has no "
    "'resolved' value, so this is not met until a person overrides it with a reason."
)

LENDER_FIGURES = (
    "foreclosure_claim",
    "foreclosure_net_recovery",
    "foreclosure_loss",
    "target_payment",
    "modification_payment_reduction_monthly",
    "modification_payment_reduction_total",
    "modification_expected_redefault_loss",
    "modification_cost",
    "modification_advantage",
)


# --- what the rules read ---------------------------------------------------------------------


@dataclass(frozen=True)
class Fact:
    """A figure the rules use and where it was read (a document line or the loan record)."""

    value: Decimal
    evidence: tuple[Evidence, ...] = ()


@dataclass(frozen=True)
class Judgement:
    """A judgement from the hardship profile. ``value`` is None when the letter was not read;
    ``confirmed`` says a person confirmed (or corrected) it, which is what the rules need."""

    value: str | None
    confirmed: bool
    evidence: tuple[Evidence, ...] = ()


@dataclass(frozen=True)
class RuleInputs:
    duration: Judgement = Judgement(None, False)
    intent: Judgement = Judgement(None, False)
    surplus: Fact | None = None  # monthly surplus or deficit, on the rule set's basis
    arrears: Fact | None = None
    contractual_payment: Fact | None = None
    gross_monthly_income: Fact | None = None  # documented
    unpaid_balance: Fact | None = None
    months_delinquent: Fact | None = None


# --- what the rules return -------------------------------------------------------------------

Condition = dict[str, Any]


@dataclass(frozen=True)
class OptionOutcome:
    option: str
    order_no: int
    status: str
    conditions: list[Condition]


@dataclass(frozen=True)
class RulesOutcome:
    options: list[OptionOutcome]
    calcs: list[Calc]
    # The lender view's settings as stored, and which figures make it (empty when incomplete).
    lender_settings: dict[str, Any]
    lender_figures: list[str]


@dataclass
class _Evaluation:
    status: str
    values: dict[str, str] = field(default_factory=dict)
    evidence: list[Evidence] = field(default_factory=list)
    note: str | None = None


def _calc(
    name: str,
    value: Decimal,
    unit: str,
    formula: str,
    inputs: Mapping[str, Decimal | str],
    working: str,
    version: str,
    evidence: tuple[Evidence, ...] = (),
) -> Calc:
    return Calc(
        name=name,
        value=value,
        unit=unit,
        formula=formula,
        inputs={k: plain(v) if isinstance(v, Decimal) else v for k, v in inputs.items()},
        working=working,
        config_version=version,
        evidence=evidence,
    )


def _pct(value: Decimal) -> str:
    return f"{plain(value.normalize())}%"


class _Engine:
    def __init__(self, rules: RuleSetConfig, inputs: RuleInputs) -> None:
        self.rules = rules
        self.i = inputs
        self.version = f"rule_set@{rules.version}"
        self.calcs: list[Calc] = []
        self.by_name: dict[str, Calc] = {}

    def add(self, calc: Calc) -> Calc:
        self.calcs.append(calc)
        self.by_name[calc.name] = calc
        return calc

    # -- figures the rules compare with --

    def target_payment(self) -> Calc | None:
        income = self.i.gross_monthly_income
        if income is None:
            return None
        pct = self.rules.setting_value("target_payment_pct")
        value = cents(income.value * pct / HUNDRED)
        return self.add(
            _calc(
                "target_payment",
                value,
                "usd",
                "target payment percentage x documented gross monthly income",
                {"percentage": pct, "gross_monthly_income": income.value},
                f"{_pct(pct)} x {money(income.value)} = {money(value)}",
                self.version,
                income.evidence,
            )
        )

    def arrears_share_needed(self, months: Decimal) -> Calc | None:
        arrears = self.i.arrears
        if arrears is None:
            return None
        value = cents(arrears.value / months)
        return self.add(
            _calc(
                "repayment_plan_surplus_needed",
                value,
                "usd",
                "arrears / number of months to catch up",
                {"arrears": arrears.value, "months": months},
                f"{money(arrears.value)} / {plain(months)} = {money(value)}",
                self.version,
                arrears.evidence,
            )
        )

    # -- the evaluators --

    def judgement(self, item: Judgement, name: str, allowed: list[str]) -> _Evaluation:
        shown = item.value if item.value is not None else "not read"
        if item.value is None:
            return _Evaluation(NOT_EVALUABLE, {name: shown}, [], NOT_READ)
        if not item.confirmed:
            return _Evaluation(
                NEEDS_CONFIRMATION,
                {name: shown, "confirmed": "no"},
                list(item.evidence),
                UNCONFIRMED,
            )
        status = MET if item.value in allowed else NOT_MET
        return _Evaluation(status, {name: shown}, list(item.evidence))

    def hardship_resolved(self) -> _Evaluation:
        found = self.judgement(self.i.duration, "duration", [])
        if found.status == NOT_MET:  # confirmed, and the profile has no "resolved" value
            found.note = NO_RESOLVED_VALUE
        return found

    def surplus_figures(self) -> tuple[Fact | None, str | None]:
        if self.i.surplus is None:
            return None, "Needs the hardship budget's monthly surplus or deficit."
        return self.i.surplus, None

    def surplus_at_least_arrears_share(self, spec: ConditionSpec) -> _Evaluation:
        surplus, missing = self.surplus_figures()
        months = self.rules.setting_value(spec.setting or "repayment_plan_months")
        needed = self.arrears_share_needed(months)
        if surplus is None or needed is None:
            return _Evaluation(
                NOT_EVALUABLE, {}, [], missing or "Needs the mortgage statement's past due amount."
            )
        status = MET if surplus.value >= needed.value else NOT_MET
        return _Evaluation(
            status,
            {
                "surplus": plain(surplus.value),
                "arrears": needed.inputs["arrears"],
                "needed": plain(needed.value),
            },
            [*surplus.evidence, *needed.evidence],
        )

    def surplus_at_least(self, spec: ConditionSpec) -> _Evaluation:
        surplus, missing = self.surplus_figures()
        if surplus is None:
            return _Evaluation(NOT_EVALUABLE, {}, [], missing)
        floor = self.rules.setting_value(spec.setting or "deferral_minimum_surplus")
        status = MET if surplus.value >= floor else NOT_MET
        return _Evaluation(
            status,
            {"surplus": plain(surplus.value), "minimum": plain(floor)},
            list(surplus.evidence),
        )

    def months_delinquent_at_most(self, spec: ConditionSpec) -> _Evaluation:
        months = self.i.months_delinquent
        if months is None:
            return _Evaluation(NOT_EVALUABLE, {}, [], "Needs the loan record's months delinquent.")
        limit = self.rules.setting_value(spec.setting or "max_months_delinquent")
        status = MET if months.value <= limit else NOT_MET
        return _Evaluation(
            status,
            {"months_delinquent": plain(months.value), "limit": plain(limit)},
            list(months.evidence),
        )

    def target_payment_below_contractual(self) -> _Evaluation:
        target = self.by_name.get("target_payment")
        payment = self.i.contractual_payment
        if target is None or payment is None:
            missing = (
                "the pay stub's gross pay" if target is None else "the mortgage statement's payment"
            )
            return _Evaluation(NOT_EVALUABLE, {}, [], f"Needs {missing}.")
        status = MET if target.value < payment.value else NOT_MET
        income = self.i.gross_monthly_income
        return _Evaluation(
            status,
            {
                "gross_monthly_income": plain(income.value) if income else "",
                "target_payment": plain(target.value),
                "contractual_payment": plain(payment.value),
            },
            [*target.evidence, *payment.evidence],
        )

    def condition(self, spec: ConditionSpec) -> Condition:
        if spec.kind == "hardship_resolved":
            found = self.hardship_resolved()
        elif spec.kind == "duration_is":
            found = self.judgement(self.i.duration, "duration", spec.allowed)
        elif spec.kind == "intent_is":
            found = self.judgement(self.i.intent, "intent", spec.allowed)
        elif spec.kind == "surplus_at_least_arrears_share":
            found = self.surplus_at_least_arrears_share(spec)
        elif spec.kind == "surplus_at_least":
            found = self.surplus_at_least(spec)
        elif spec.kind == "months_delinquent_at_most":
            found = self.months_delinquent_at_most(spec)
        elif spec.kind == "target_payment_below_contractual":
            found = self.target_payment_below_contractual()
        elif spec.kind == "no_earlier_option_met":
            found = _Evaluation(MET)  # recompute sets it from the options before
        else:  # none_defined
            found = _Evaluation(NOT_EVALUABLE, {}, [], "The sample rule set defines no conditions.")
        out: Condition = {
            "id": spec.id,
            "label": spec.label,
            "expression": spec.expression,
            "values": found.values,
            "passage_id": spec.passage_id,
            "status": found.status,
            "evidence": found.evidence,
        }
        if found.note:
            out["note"] = found.note
        if spec.kind == "no_earlier_option_met":
            out["derived"] = True
        return out

    # -- the lender view --

    def lender_view(self) -> tuple[dict[str, Any], list[str]]:
        view = self.rules.lender_view
        settings: dict[str, Any] = {
            "property_value": plain(view.property_value.value),
            "liquidation_discount_pct": plain(view.liquidation_discount_pct.value),
            "foreclosure_and_carrying_costs": plain(view.foreclosure_and_carrying_costs.value),
            "horizon_months": view.horizon_months.value,
            "redefault_chance_pct": plain(view.redefault_chance_pct.value),
        }
        balance, arrears = self.i.unpaid_balance, self.i.arrears
        payment = self.i.contractual_payment
        target = self.by_name.get("target_payment")
        if balance is None or arrears is None or payment is None or target is None:
            return settings, []
        evidence = (*balance.evidence, *arrears.evidence)
        claim = balance.value + arrears.value
        self.add(
            _calc(
                "foreclosure_claim",
                claim,
                "usd",
                "unpaid balance + arrears",
                {"unpaid_balance": balance.value, "arrears": arrears.value},
                f"{money(balance.value)} + {money(arrears.value)} = {money(claim)}",
                self.version,
                evidence,
            )
        )
        value, pct = view.property_value.value, view.liquidation_discount_pct.value
        costs = view.foreclosure_and_carrying_costs.value
        discount = cents(value * pct / HUNDRED)
        recovery = value - discount - costs
        self.add(
            _calc(
                "foreclosure_net_recovery",
                recovery,
                "usd",
                "property value less the liquidation discount, less foreclosure and carrying costs",
                {"property_value": value, "liquidation_discount_pct": pct, "costs": costs},
                f"{money(value)} - {_pct(pct)} ({money(discount)}) - {money(costs)} = "
                f"{money(recovery)}",
                self.version,
            )
        )
        loss = claim - recovery
        self.add(
            _calc(
                "foreclosure_loss",
                loss,
                "usd",
                "claim - net recovery",
                {"claim": claim, "net_recovery": recovery},
                f"{money(claim)} - {money(recovery)} = {money(loss)}",
                self.version,
            )
        )
        reduction = max(payment.value - target.value, Decimal(0))
        months = Decimal(view.horizon_months.value)
        self.add(
            _calc(
                "modification_payment_reduction_monthly",
                reduction,
                "usd",
                "contractual payment - target payment (never below zero)",
                {"contractual_payment": payment.value, "target_payment": target.value},
                f"{money(payment.value)} - {money(target.value)} = {money(reduction)}",
                self.version,
                payment.evidence,
            )
        )
        over_horizon = reduction * months
        self.add(
            _calc(
                "modification_payment_reduction_total",
                over_horizon,
                "usd",
                "monthly payment reduction x horizon months",
                {"monthly_reduction": reduction, "horizon_months": months},
                f"{money(reduction)} x {plain(months)} = {money(over_horizon)}",
                self.version,
            )
        )
        chance = view.redefault_chance_pct.value
        exposed = max(loss, Decimal(0))
        redefault = cents(exposed * chance / HUNDRED)
        self.add(
            _calc(
                "modification_expected_redefault_loss",
                redefault,
                "usd",
                "foreclosure loss x chance of re-default",
                {"foreclosure_loss": exposed, "redefault_chance_pct": chance},
                f"{money(exposed)} x {_pct(chance)} = {money(redefault)}",
                self.version,
            )
        )
        cost = over_horizon + redefault
        self.add(
            _calc(
                "modification_cost",
                cost,
                "usd",
                "payment reduction over the horizon + expected re-default loss",
                {"payment_reduction_total": over_horizon, "expected_redefault_loss": redefault},
                f"{money(over_horizon)} + {money(redefault)} = {money(cost)}",
                self.version,
            )
        )
        advantage = loss - cost
        self.add(
            _calc(
                "modification_advantage",
                advantage,
                "usd",
                "foreclosure loss - modification cost",
                {"foreclosure_loss": loss, "modification_cost": cost},
                f"{money(loss)} - {money(cost)} = {money(advantage)}",
                self.version,
            )
        )
        return settings, [n for n in LENDER_FIGURES if n in self.by_name]


def evaluate(rules: RuleSetConfig, inputs: RuleInputs) -> RulesOutcome:
    """Decide every condition, set each option's status in waterfall order, and compute the lender
    view. Two runs on the same inputs and rule set give the same result."""
    engine = _Engine(rules, inputs)
    engine.target_payment()
    grouped = [[engine.condition(spec) for spec in option.conditions] for option in rules.options]
    planned = recompute(grouped)
    options = [
        OptionOutcome(option.option.value, number, status, conditions)
        for number, (option, (status, conditions)) in enumerate(
            zip(rules.options, planned, strict=True), start=1
        )
    ]
    settings, figures = engine.lender_view()
    return RulesOutcome(options, engine.calcs, settings, figures)

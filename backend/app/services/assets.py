"""Asset and liability analysis (Feature 3, Feature Design 3.3 to 3.8).

Pure code over plain inputs: no database, no model. The transactions arrive already labelled (by the
labelling call, or by a reviewer who changed a label), and this module does everything else:

* matches payroll deposits to pay stubs (employer in the description, amount within the tolerance,
  date within a few days of a pay date, projected from the stub's pay date and frequency);
* flags large deposits, overdraft or returned-item fees and lines the labeller could not place;
* finds recurring debts (the same payee in two or more statement months, amounts within a dollar)
  and reconciles them with the credit report's liabilities;
* totals documented assets, compares them with the funds needed, and computes the candidate
  front-end ratio, DTI and LTV.

Every figure is a ``Calc`` with its formula, inputs and working (rule 1), and points at the line it
came from (rule 2). Flag messages are templates from ``thresholds.yaml`` (rule 3), and every
setting is read from there (rule 4). The results are candidates for the underwriter, never a
decision.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import date
from decimal import Decimal
from typing import Any, Literal
from uuid import UUID

from app.services.analysis_config import AnalysisConfig
from app.services.calculations import Calc, money, percent, plain, six_places
from app.services.income import FlagResult

Evidence = dict[str, Any]

RECURRING_CATEGORIES = {
    "loan payment": "installment",
    "credit card payment": "revolving",
    "housing payment": "rent",
}
HUNDRED = Decimal(100)
RENT_REASON = "Current rent on a purchase of a primary residence."
NO_PAYMENT_REASON = "The credit report shows no monthly payment."
BANK_REASON = "Recurring payment found in the bank statements."
BANK_ONLY_REASON = (
    "Recurring payment found in the bank statements, not on the credit report: "
    "the underwriter decides whether it counts."
)
CREDIT_REASON = "Credit report liability with a monthly payment above zero."
BOTH_REASON = "On the credit report and in the bank statements."


# --- inputs ---------------------------------------------------------------------------------


@dataclass(frozen=True)
class TxnInput:
    """One statement line with its label. ``amount`` is the size; ``direction`` says which way."""

    id: UUID | None
    document_id: UUID
    line_ref: str
    account_last4: str | None
    posted_on: date
    description: str
    amount: Decimal
    direction: Literal["credit", "debit"] | str
    category: str
    counterparty: str | None = None
    needs_review: bool = False
    sourced: bool = False


@dataclass(frozen=True)
class StatementInput:
    document_id: UUID
    account_last4: str | None
    period_start: date | None
    period_end: date | None
    opening_balance: Decimal | None
    closing_balance: Decimal | None
    closing_lines: tuple[str, ...]
    transactions: tuple[TxnInput, ...]


@dataclass(frozen=True)
class StubInput:
    """A pay stub's facts for payroll matching (``net_pay`` as a reviewer corrected it)."""

    document_id: UUID
    employer: str
    pay_date: date | None
    period_days: int | None  # 14 for biweekly: the gap between pay dates
    net_pay: Decimal | None
    lines: tuple[str, ...]


@dataclass(frozen=True)
class LiabilityInput:
    """A tradeline from the credit report."""

    document_id: UUID
    creditor: str
    kind: str
    balance: Decimal | None
    monthly_payment: Decimal | None
    lines: tuple[str, ...]


@dataclass(frozen=True)
class ScenarioInput:
    purpose: str
    occupancy: str
    property_value: Decimal
    loan_amount: Decimal
    proposed_housing_payment: Decimal
    funds_to_close: Decimal


@dataclass(frozen=True)
class IncomeInput:
    """Candidate monthly income from the income analysis, and the components it left out."""

    candidate_monthly: Decimal | None
    excluded_monthly: Mapping[str, Decimal] = field(default_factory=dict)
    calc_name: str = "candidate_monthly_income"


@dataclass(frozen=True)
class AssetInputs:
    statements: tuple[StatementInput, ...]
    stubs: tuple[StubInput, ...]
    liabilities: tuple[LiabilityInput, ...]
    scenario: ScenarioInput | None
    income: IncomeInput | None
    borrower_names: tuple[str, ...]
    # A person's include (True) or exclude (False) of a debt, by creditor name. It replaces what the
    # system decided, and the ratios are computed with it.
    obligation_overrides: tuple[tuple[str, bool], ...] = ()


# --- results --------------------------------------------------------------------------------


@dataclass(frozen=True)
class PayrollMatch:
    stub_document_id: UUID
    pay_date: date  # the pay date the deposit was matched to (projected from the stub)
    net_pay: Decimal
    working: str


@dataclass(frozen=True)
class TxnResult:
    input: TxnInput
    payroll_match: PayrollMatch | None = None
    large_deposit: bool = False

    @property
    def sourced(self) -> bool:
        return self.input.sourced


@dataclass(frozen=True)
class AccountResult:
    account_last4: str | None
    document_id: UUID
    period_end: date | None
    closing_balance: Decimal | None
    lines: tuple[str, ...]


@dataclass(frozen=True)
class ObligationResult:
    creditor: str
    kind: str
    monthly_payment: Decimal
    balance: Decimal | None
    source: Literal["bank", "credit_report", "both"]
    counts_toward_dti: bool
    reason: str
    evidence: tuple[Evidence, ...] = ()
    # Set when a person included or excluded the debt: what the system decided before that (rule 6).
    system_counts: bool | None = None


@dataclass
class AssetOutcome:
    accounts: list[AccountResult]
    transactions: list[TxnResult]
    obligations: list[ObligationResult]
    calcs: list[Calc]
    flags: list[FlagResult]

    def calc(self, name: str) -> Calc | None:
        return next((c for c in self.calcs if c.name == name), None)


# --- small helpers --------------------------------------------------------------------------


def _words(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", text.lower())


def _same_name(a: str, b: str) -> bool:
    """Two names are the same when their words are, or one starts with the other's first two."""
    wa, wb = _words(a), _words(b)
    if not wa or not wb:
        return False
    if wa == wb:
        return True
    short, long_ = (wa, wb) if len(wa) <= len(wb) else (wb, wa)
    lead = short[:2]
    return long_[: len(lead)] == lead


def _employer_in(description: str, employer: str, suffixes: Sequence[str]) -> bool:
    drop = {s.lower().strip(".,") for s in suffixes}
    lead = [w for w in _words(employer) if w not in drop][:2]
    return bool(lead) and set(lead) <= set(_words(description))


def _level(share: Decimal) -> str:
    return f"{(share * HUNDRED).normalize():f}%"


def _calc(
    name: str,
    value: Decimal,
    unit: str,
    formula: str,
    inputs: Mapping[str, Decimal | str],
    working: str,
    version: str,
    evidence: Sequence[Evidence] = (),
) -> Calc:
    return Calc(
        name=name,
        value=value,
        unit=unit,
        formula=formula,
        inputs={k: plain(v) if isinstance(v, Decimal) else v for k, v in inputs.items()},
        working=working,
        config_version=version,
        evidence=tuple(evidence),
    )


# --- the ratios (also used to recompute after a change and for what-if) ---------------------


def _ratio(
    name: str,
    numerator: Decimal,
    denominator: Decimal,
    shown: str,
    formula: str,
    version: str,
    inputs: Mapping[str, Decimal | str],
    evidence: Sequence[Evidence],
) -> Calc:
    value = six_places(numerator / denominator)
    return _calc(
        name, value, "ratio", formula, inputs, f"{shown} = {percent(value)}", version, evidence
    )


def ratios(
    *,
    scenario: ScenarioInput | None,
    income: IncomeInput | None,
    obligations_monthly: Decimal,
    version: str,
    review_level: Decimal,
) -> list[Calc]:
    """Front-end ratio, DTI (with each left-out income component counted) and LTV.

    A ratio whose inputs are missing, or whose income is zero, is simply not returned; the caller
    says what was missing. ``review_level`` is not used to compute anything here: it is accepted so
    callers that recompute pass one set of settings.
    """
    del review_level
    out: list[Calc] = []
    if scenario is None:
        return out
    housing, value = scenario.proposed_housing_payment, scenario.property_value
    source = [{"source": "loan scenario"}]
    out.append(
        _ratio(
            "ltv",
            scenario.loan_amount,
            value,
            f"{money(scenario.loan_amount)} / {money(value)}",
            "loan amount / property value",
            version,
            {"loan_amount": scenario.loan_amount, "property_value": value},
            source,
        )
    )
    candidate = income.candidate_monthly if income else None
    if income is None or candidate is None or candidate <= 0:
        return out
    from_income = [*source, {"source": "income analysis", "calculation": income.calc_name}]
    debts = housing + obligations_monthly
    out.append(
        _ratio(
            "front_end_ratio",
            housing,
            candidate,
            f"{money(housing)} / {money(candidate)}",
            "proposed housing payment / candidate monthly income",
            version,
            {"housing_payment": housing, "monthly_income": candidate},
            from_income,
        )
    )
    shown = f"({money(housing)} + {money(obligations_monthly)})"
    out.append(
        _ratio(
            "dti",
            debts,
            candidate,
            f"{shown} / {money(candidate)}",
            "(proposed housing payment + monthly obligations) / candidate monthly income",
            version,
            {
                "housing_payment": housing,
                "monthly_obligations": obligations_monthly,
                "monthly_income": candidate,
            },
            from_income,
        )
    )
    for component, monthly in sorted(income.excluded_monthly.items()):
        if monthly <= 0:
            continue
        counted = candidate + monthly
        out.append(
            _ratio(
                f"dti_with_{component}",
                debts,
                counted,
                f"{shown} / {money(counted)}",
                f"DTI with {component} counted in income",
                version,
                {
                    "debts": debts,
                    "monthly_income": candidate,
                    f"{component}_monthly": monthly,
                },
                from_income,
            )
        )
    return out


# --- the analysis ---------------------------------------------------------------------------


class _Analysis:
    def __init__(self, inputs: AssetInputs, cfg: AnalysisConfig) -> None:
        self.i = inputs
        self.t = cfg.thresholds
        self.suffixes = cfg.income.employer_suffixes.value
        self.version = cfg.calc_version("thresholds")
        self.flags: list[FlagResult] = []
        self.calcs: list[Calc] = []

    # -- flags --

    def flag(
        self, code: str, key: str, evidence: Sequence[Evidence] = (), **values: object
    ) -> None:
        severity, message = self.t.flag(code, **values)
        self.flags.append(FlagResult(code, key, severity, message, tuple(evidence)))

    def cannot(self, what: str, missing: str) -> None:
        self.flag("AL-I101", f"{what}", what=what, missing=missing)

    # -- documented assets and funds --

    def accounts(self) -> list[AccountResult]:
        latest: dict[str | None, StatementInput] = {}
        for s in self.i.statements:
            held = latest.get(s.account_last4)
            if held is None or (s.period_end or date.min) >= (held.period_end or date.min):
                latest[s.account_last4] = s
        return [
            AccountResult(
                s.account_last4, s.document_id, s.period_end, s.closing_balance, s.closing_lines
            )
            for _, s in sorted(latest.items(), key=lambda kv: kv[0] or "")
        ]

    def assets_and_funds(self, accounts: list[AccountResult]) -> None:
        counted = [a for a in accounts if a.closing_balance is not None]
        assets: Decimal | None = None
        if accounts and not counted:
            self.cannot("documented assets", "a closing balance")
        elif counted:
            assets = sum((a.closing_balance for a in counted if a.closing_balance), Decimal(0))
            parts = " + ".join(money(a.closing_balance) for a in counted if a.closing_balance)
            evidence = [
                {
                    "document_id": str(a.document_id),
                    "field": "closing_balance",
                    "line_ids": list(a.lines),
                }
                for a in counted
            ]
            shown = parts if len(counted) == 1 else f"{parts} = {money(assets)}"
            if len(counted) == 1:
                shown = money(assets)
            self.calcs.append(
                _calc(
                    "documented_assets",
                    assets,
                    "usd",
                    "sum of the latest closing balance of each account",
                    {
                        f"account_{a.account_last4 or 'unknown'}": a.closing_balance or Decimal(0)
                        for a in counted
                    },
                    shown,
                    self.version,
                    evidence,
                )
            )
        scenario = self.i.scenario
        if scenario is None:
            return
        needed = scenario.funds_to_close
        scenario_evidence = [{"source": "loan scenario", "field": "funds_to_close"}]
        self.calcs.append(
            _calc(
                "funds_to_close",
                needed,
                "usd",
                "estimated funds needed to close (entered by hand)",
                {"funds_to_close": needed},
                money(needed),
                self.version,
                scenario_evidence,
            )
        )
        if assets is None:
            return
        shortfall = max(Decimal(0), needed - assets)
        working = (
            f"{money(needed)} - {money(assets)} = {money(shortfall)}"
            if shortfall > 0
            else f"{money(assets)} covers {money(needed)}: no shortfall"
        )
        self.calcs.append(
            _calc(
                "funds_shortfall",
                shortfall,
                "usd",
                "funds needed - documented assets, never below zero",
                {"funds_to_close": needed, "documented_assets": assets},
                working,
                self.version,
                scenario_evidence,
            )
        )
        if shortfall > 0:
            self.flag(
                "AL-W105",
                "funds",
                scenario_evidence,
                assets=money(assets),
                shortfall=money(shortfall),
                needed=money(needed),
            )

    # -- transactions --

    def match_payroll(self, t: TxnInput) -> PayrollMatch | None:
        tolerance, window = self.t.payroll_match_tolerance.value, self.t.payroll_match_days.value
        for stub in self.i.stubs:
            if stub.pay_date is None or stub.net_pay is None:
                continue
            if not _employer_in(t.description, stub.employer, self.suffixes):
                continue
            if abs(t.amount - stub.net_pay) > tolerance:
                continue
            offset = (t.posted_on - stub.pay_date).days
            period = stub.period_days
            # The nearest pay date, either way: the stub's own, or one projected by its frequency.
            steps = (2 * offset + period) // (2 * period) if period else 0
            pay_date = date.fromordinal(stub.pay_date.toordinal() + steps * (period or 0))
            if abs((t.posted_on - pay_date).days) > window:
                continue
            working = (
                f"{money(t.amount)} on {t.posted_on.isoformat()} is within {money(tolerance)} of "
                f"net pay {money(stub.net_pay)} and within {window} days of the pay date "
                f"{pay_date.isoformat()}"
            )
            return PayrollMatch(stub.document_id, pay_date, stub.net_pay, working)
        return None

    def payroll_calc(self, t: TxnInput, match: PayrollMatch, evidence: Sequence[Evidence]) -> None:
        stub = next(s for s in self.i.stubs if s.document_id == match.stub_document_id)
        self.calcs.append(
            _calc(
                "payroll_match",
                t.amount,
                "usd",
                "deposit within the tolerance of the pay stub's net pay, near a pay date",
                {"deposit": t.amount, "net_pay": match.net_pay},
                match.working,
                self.version,
                [
                    *evidence,
                    {
                        "document_id": str(stub.document_id),
                        "field": "net_pay_current",
                        "line_ids": list(stub.lines),
                    },
                ],
            )
        )

    def large_deposit_calc(
        self, t: TxnInput, minimum: Decimal, evidence: Sequence[Evidence]
    ) -> None:
        self.calcs.append(
            _calc(
                "large_deposit",
                t.amount,
                "usd",
                "credit at or above the large-deposit minimum that is not payroll or the "
                "borrower's own transfer",
                {"deposit": t.amount, "minimum": minimum},
                f"{money(t.amount)} is {money(minimum)} or more, and it is not matched to payroll "
                "or a transfer between the borrower's own accounts",
                self.version,
                evidence,
            )
        )

    def own_account(self, counterparty: str | None) -> bool:
        return bool(counterparty) and any(
            _same_name(counterparty or "", name) for name in self.i.borrower_names
        )

    def transactions(self) -> list[TxnResult]:
        usable_stubs = any(s.pay_date and s.net_pay is not None for s in self.i.stubs)
        minimum = self.t.large_deposit_minimum.value
        results: list[TxnResult] = []
        unsure = 0
        everything = sorted(
            (t for s in self.i.statements for t in s.transactions),
            key=lambda t: (t.posted_on, t.document_id.int, t.line_ref),
        )
        for t in everything:
            evidence = [
                {
                    "document_id": str(t.document_id),
                    "field": "transaction",
                    "line_ids": [t.line_ref],
                }
            ]
            when = t.posted_on.isoformat()
            match = None
            large = False
            if t.needs_review:
                unsure += 1
            if t.direction == "credit":
                if t.category == "payroll deposit" or any(
                    _employer_in(t.description, s.employer, self.suffixes) for s in self.i.stubs
                ):
                    match = self.match_payroll(t)
                    if match is not None:
                        self.payroll_calc(t, match, evidence)
                if t.category == "payroll deposit" and match is None and usable_stubs:
                    self.flag(
                        "AL-W104",
                        f"{t.document_id}:{t.line_ref}",
                        evidence,
                        amount=money(t.amount),
                        date=when,
                    )
                if (
                    t.amount >= minimum
                    and t.category != "payroll deposit"
                    and match is None
                    and not self.own_account(t.counterparty)
                ):
                    large = True
                    self.large_deposit_calc(t, minimum, evidence)
                    if not t.sourced:
                        self.flag(
                            "AL-W101",
                            f"{t.document_id}:{t.line_ref}",
                            evidence,
                            amount=money(t.amount),
                            date=when,
                        )
            elif t.category == "overdraft or returned-item fee":
                self.flag(
                    "AL-W102",
                    f"{t.document_id}:{t.line_ref}",
                    evidence,
                    amount=money(t.amount),
                    date=when,
                )
            results.append(TxnResult(t, match, large))
        if unsure:
            code = "AL-W107:one" if unsure == 1 else "AL-W107"
            self.flag(code, "labels", count=unsure)
        return results

    # -- obligations --

    def bank_debts(self) -> list[ObligationResult]:
        tolerance = self.t.recurring_debit_tolerance.value
        needed = self.t.recurring_debit_min_months.value
        groups: list[list[TxnInput]] = []
        candidates = sorted(
            (
                t
                for s in self.i.statements
                for t in s.transactions
                if t.direction == "debit" and t.category in RECURRING_CATEGORIES
            ),
            key=lambda t: t.posted_on,
        )
        for t in candidates:
            name = t.counterparty or t.description
            for group in groups:
                if group[0].category == t.category and _same_name(
                    group[0].counterparty or group[0].description, name
                ):
                    group.append(t)
                    break
            else:
                groups.append([t])
        out: list[ObligationResult] = []
        scenario = self.i.scenario
        purchase = bool(
            scenario
            and scenario.purpose.lower() == "purchase"
            and "primary" in scenario.occupancy.lower()
        )
        for group in groups:
            latest = group[-1]
            months = {
                (t.posted_on.year, t.posted_on.month)
                for t in group
                if abs(t.amount - latest.amount) <= tolerance
            }
            if len(months) < needed:
                continue
            kind = RECURRING_CATEGORIES[latest.category]
            counts, reason = True, BANK_REASON
            if kind == "rent" and self.t.dti_exclude_rent_on_purchase.value and purchase:
                counts, reason = False, RENT_REASON
            out.append(
                ObligationResult(
                    creditor=latest.counterparty or latest.description,
                    kind=kind,
                    monthly_payment=latest.amount,
                    balance=None,
                    source="bank",
                    counts_toward_dti=counts,
                    reason=reason,
                    evidence=tuple(
                        {
                            "document_id": str(t.document_id),
                            "field": "transaction",
                            "line_ids": [t.line_ref],
                        }
                        for t in group
                    ),
                )
            )
        return out

    def obligations(self) -> list[ObligationResult]:
        bank = self.bank_debts()
        minimum = self.t.dti_min_liability_payment.value
        have_report = bool(self.i.liabilities)
        merged: list[ObligationResult] = []
        matched: set[int] = set()
        for line in self.i.liabilities:
            evidence: tuple[Evidence, ...] = (
                {
                    "document_id": str(line.document_id),
                    "field": "tradeline",
                    "line_ids": list(line.lines),
                },
            )
            payment = line.monthly_payment
            counts = payment is not None and payment > minimum
            twin = next(
                (
                    n
                    for n, b in enumerate(bank)
                    if n not in matched
                    and b.kind != "rent"
                    and _same_name(b.creditor, line.creditor)
                ),
                None,
            )
            if twin is not None:
                matched.add(twin)
                evidence += bank[twin].evidence
            if not counts:
                reason = NO_PAYMENT_REASON
            else:
                reason = BOTH_REASON if twin is not None else CREDIT_REASON
            merged.append(
                ObligationResult(
                    creditor=line.creditor,
                    kind=line.kind,
                    monthly_payment=payment or Decimal("0.00"),
                    balance=line.balance,
                    source="both" if twin is not None else "credit_report",
                    counts_toward_dti=counts,
                    reason=reason,
                    evidence=evidence,
                )
            )
        for n, b in enumerate(bank):
            if n in matched:
                continue
            if have_report and b.kind != "rent":
                self.flag(
                    "AL-W103",
                    b.creditor,
                    b.evidence[:1],
                    creditor=b.creditor,
                    amount=money(b.monthly_payment),
                )
                b = ObligationResult(
                    b.creditor,
                    b.kind,
                    b.monthly_payment,
                    b.balance,
                    b.source,
                    b.counts_toward_dti,
                    BANK_ONLY_REASON,
                    b.evidence,
                )
            merged.append(b)
        return sorted(merged, key=lambda o: (o.creditor.lower(), o.source))

    def with_overrides(self, found: list[ObligationResult]) -> list[ObligationResult]:
        out: list[ObligationResult] = []
        for o in found:
            wanted = next(
                (
                    keep
                    for name, keep in self.i.obligation_overrides
                    if _same_name(o.creditor, name)
                ),
                None,
            )
            if wanted is None or wanted == o.counts_toward_dti:
                out.append(o)
            else:
                out.append(replace(o, counts_toward_dti=wanted, system_counts=o.counts_toward_dti))
        return out

    def run(self) -> AssetOutcome:
        accounts = self.accounts()
        self.assets_and_funds(accounts)
        txns = self.transactions()
        obligations = self.with_overrides(self.obligations())
        counted = [o for o in obligations if o.counts_toward_dti]
        total = sum((o.monthly_payment for o in counted), Decimal(0))
        working = (
            " + ".join(money(o.monthly_payment) for o in counted) + f" = {money(total)}"
            if counted
            else "no debts count toward DTI"
        )
        self.calcs.append(
            _calc(
                "monthly_obligations",
                total,
                "usd",
                "sum of the monthly payments of obligations that count toward DTI",
                {o.creditor: o.monthly_payment for o in counted} or {"obligations": "none"},
                working,
                self.version,
                [e for o in counted for e in o.evidence[:1]],
            )
        )
        self.ratio_calcs(total)
        return AssetOutcome(accounts, txns, obligations, self.calcs, self.flags)

    def ratio_calcs(self, obligations: Decimal) -> None:
        level = self.t.dti_review_level.value
        scenario, income = self.i.scenario, self.i.income
        made = ratios(
            scenario=scenario,
            income=income,
            obligations_monthly=obligations,
            version=self.version,
            review_level=level,
        )
        self.calcs.extend(made)
        have = {c.name for c in made}
        if scenario is None:
            self.cannot("front-end ratio, DTI and LTV", "the loan scenario")
        elif "dti" not in have:
            self.cannot("front-end ratio and DTI", "candidate monthly income")
        dti = next((c for c in made if c.name == "dti"), None)
        if dti is not None and dti.value > level:
            self.flag("AL-W106", "dti", dti.evidence, dti=percent(dti.value), level=_level(level))


# --- what if ------------------------------------------------------------------------------------


@dataclass(frozen=True)
class WhatIfChanges:
    """Changes to try on a stored analysis. A field left as ``None`` is not changed."""

    property_value: Decimal | None = None
    loan_amount: Decimal | None = None
    proposed_housing_payment: Decimal | None = None
    funds_to_close: Decimal | None = None
    monthly_income: Decimal | None = None
    # Creditors whose payment is taken out of the obligations, and a payment added to them.
    drop_obligations: tuple[str, ...] = ()
    extra_obligation_monthly: Decimal | None = None

    def changed(self) -> dict[str, str]:
        out = {
            name: f"{getattr(self, name):f}"
            for name in (
                "property_value",
                "loan_amount",
                "proposed_housing_payment",
                "funds_to_close",
                "monthly_income",
                "extra_obligation_monthly",
            )
            if getattr(self, name) is not None
        }
        if self.drop_obligations:
            out["drop_obligations"] = ", ".join(self.drop_obligations)
        return out


@dataclass
class WhatIfResult:
    """The ratios and funds shortfall with the changes applied. Nothing is stored or decided."""

    changed: dict[str, str]
    calcs: list[Calc]
    # Names in ``drop_obligations`` that matched no counted obligation.
    unmatched: list[str]

    def calc(self, name: str) -> Calc | None:
        return next((c for c in self.calcs if c.name == name), None)


def what_if(
    *,
    scenario: ScenarioInput | None,
    income: IncomeInput | None,
    obligations: Sequence[ObligationResult],
    documented_assets: Decimal | None,
    changes: WhatIfChanges,
    version: str,
    review_level: Decimal,
) -> WhatIfResult:
    """Recompute the ratios and the funds shortfall with ``changes`` applied (Researcher, FD 3.6).

    Pure and read-only: the stored analysis is not touched. The same formulas run as in the
    analysis, so a what-if with no changes returns the stored figures.
    """
    unmatched: list[str] = []
    counted = [o for o in obligations if o.counts_toward_dti]
    for name in changes.drop_obligations:
        hit = [o for o in counted if _same_name(o.creditor, name)]
        if hit:
            counted = [o for o in counted if o not in hit]
        else:
            unmatched.append(name)
    total = sum((o.monthly_payment for o in counted), Decimal(0))
    parts = [money(o.monthly_payment) for o in counted]
    extra = changes.extra_obligation_monthly
    if extra is not None:
        total += extra
        parts.append(money(extra))
    working = f"{' + '.join(parts)} = {money(total)}" if parts else "no debts count toward DTI"
    calcs = [
        _calc(
            "monthly_obligations",
            total,
            "usd",
            "sum of the monthly payments of obligations that count toward DTI (what-if)",
            {o.creditor: o.monthly_payment for o in counted}
            | ({"added": extra} if extra is not None else {}),
            working,
            version,
        )
    ]
    if scenario is not None:
        scenario = ScenarioInput(
            scenario.purpose,
            scenario.occupancy,
            changes.property_value
            if changes.property_value is not None
            else scenario.property_value,
            changes.loan_amount if changes.loan_amount is not None else scenario.loan_amount,
            (
                changes.proposed_housing_payment
                if changes.proposed_housing_payment is not None
                else scenario.proposed_housing_payment
            ),
            changes.funds_to_close
            if changes.funds_to_close is not None
            else scenario.funds_to_close,
        )
    if income is not None and changes.monthly_income is not None:
        income = IncomeInput(changes.monthly_income, income.excluded_monthly, income.calc_name)
    calcs += ratios(
        scenario=scenario,
        income=income,
        obligations_monthly=total,
        version=version,
        review_level=review_level,
    )
    if scenario is not None and documented_assets is not None:
        needed = scenario.funds_to_close
        shortfall = max(Decimal(0), needed - documented_assets)
        calcs.append(
            _calc(
                "funds_shortfall",
                shortfall,
                "usd",
                "funds needed - documented assets, never below zero (what-if)",
                {"funds_to_close": needed, "documented_assets": documented_assets},
                f"{money(needed)} - {money(documented_assets)} = {money(shortfall)}"
                if shortfall > 0
                else f"{money(documented_assets)} covers {money(needed)}: no shortfall",
                version,
            )
        )
    return WhatIfResult(changes.changed(), calcs, unmatched)


def analyze(inputs: AssetInputs, cfg: AnalysisConfig) -> AssetOutcome:
    """Everything Feature 3 computes from labelled transactions, stubs, the credit report and the
    loan scenario. Pure: the same inputs and settings always give the same result."""
    return _Analysis(inputs, cfg).run()

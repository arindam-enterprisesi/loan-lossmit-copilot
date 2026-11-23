"""The hardship budget (Feature Design 7.2 and 7.5): stated against observed, and the measures.

Pure code over plain inputs, no database and no model (the model only reads the letter; steps 6, 7
and 10 of the flow are Python, so adjusting the budget never calls it). The budget has two bases:

* **stated**: what the borrower put on the application, line by line;
* **observed**: what the bank statements show. For each budget line it is the debits of the latest
  statement month that has a debit in that line (so a mortgage paid in July and missed in
  September shows July's 1,720.00), with transfers and anything else not an expense left out. This
  rule is not in the Feature Design: it is flagged in docs/build-log.md.

From them it computes documented income (gross and net, monthly, from the pay stubs), the income
change, the surplus or deficit on both bases, the housing ratio, arrears and liquid assets, and runs
the consistency checks (stated income, the hours cut against the pay change, the application
against the letter). Every figure is a ``Calc`` with its formula, inputs and working (rule 1) and
the lines it came from (rule 2); a figure whose inputs are missing is not returned, and an
``HB-I101`` flag says what was missing. Nothing here decides anything (rule 3): a difference is
flagged for the specialist to look at.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Any
from uuid import UUID

from app.services.analysis_config import AnalysisConfig
from app.services.calculations import Calc, cents, money, percent, plain, six_places
from app.services.income import FlagResult

Evidence = dict[str, Any]
TWELVE = Decimal(12)
HUNDRED = Decimal(100)
OTHER = "Other"
# The measures in the order they are shown (the order they are computed in).
MEASURE_ORDER = (
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
)
MONTHS = [
    "",
    "January",
    "February",
    "March",
    "April",
    "May",
    "June",
    "July",
    "August",
    "September",
    "October",
    "November",
    "December",
]


# --- inputs ---------------------------------------------------------------------------------


@dataclass(frozen=True)
class StubPay:
    """One pay stub's gross and net for its pay period, and how many periods make a year."""

    document_id: UUID
    pay_date: date
    gross: Decimal
    net: Decimal
    periods_per_year: int
    gross_lines: tuple[str, ...]
    net_lines: tuple[str, ...]


@dataclass(frozen=True)
class StatedRow:
    """A row of the application: an expense or an income, as the borrower described it."""

    document_id: UUID
    description: str
    amount: Decimal
    lines: tuple[str, ...]


@dataclass(frozen=True)
class DebitLine:
    """A bank statement debit with the category it was labelled (and a person may have changed)."""

    document_id: UUID
    line_ref: str
    posted_on: date
    amount: Decimal
    category: str


@dataclass(frozen=True)
class Balance:
    """An account's closing balance on its newest statement."""

    document_id: UUID
    account_last4: str | None
    closing: Decimal
    lines: tuple[str, ...]


@dataclass(frozen=True)
class Figure:
    """A single amount read from a document, with where it was read."""

    value: Decimal
    document_id: UUID
    lines: tuple[str, ...]


@dataclass(frozen=True)
class LetterFacts:
    """What the hardship profile says, as confirmed by the specialist where they confirmed it."""

    primary_reason: str | None  # a hardship category key
    intent: str | None  # keep, sell or unsure
    hours: tuple[Decimal, Decimal] | None  # the weekly hours before and after a cut


@dataclass(frozen=True)
class BudgetInputs:
    stubs: tuple[StubPay, ...] = ()
    stated_expenses: tuple[StatedRow, ...] = ()
    stated_income: tuple[StatedRow, ...] = ()
    application_reasons: tuple[str, ...] = ()  # printed, as ticked
    application_intent: str | None = None
    has_statements: bool = False
    debits: tuple[DebitLine, ...] = ()
    balances: tuple[Balance, ...] = ()
    contractual_payment: Figure | None = None
    arrears: Figure | None = None
    letter: LetterFacts | None = None
    # Hardship category label (lower case) -> key, to read the ticked reasons.
    reason_keys: Mapping[str, str] = field(default_factory=dict)
    # A person's adjustment of a line's observed amount, by budget line: (amount, reason).
    adjustments: Mapping[str, tuple[Decimal, str]] = field(default_factory=dict)


# --- results --------------------------------------------------------------------------------


@dataclass(frozen=True)
class LineResult:
    category: str
    stated: Decimal | None
    observed: Decimal | None
    observed_month: str | None  # "2026-07": the statement month the observed amount came from
    adjusted: Decimal | None
    adjustment_reason: str | None
    flagged: bool
    stated_calc: Calc | None
    observed_calc: Calc | None

    @property
    def effective_observed(self) -> Decimal | None:
        """What counts on the observed basis: the person's adjustment, else the statements'."""
        return self.adjusted if self.adjusted is not None else self.observed


@dataclass
class BudgetOutcome:
    lines: list[LineResult]
    calcs: list[Calc]
    flags: list[FlagResult]

    def calc(self, name: str) -> Calc | None:
        return next((c for c in self.calcs if c.name == name), None)


# --- small helpers --------------------------------------------------------------------------


def slug(category: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", category.lower()).strip("_")


def month_label(year: int, month: int) -> str:
    return f"{year}-{month:02d}"


def month_name(label: str) -> str:
    year, month = label.split("-")
    return f"{MONTHS[int(month)]} {year}"


def monthly(amount: Decimal, periods_per_year: int) -> Decimal:
    return cents(amount * periods_per_year / TWELVE)


def hours_change(texts: Sequence[str]) -> tuple[Decimal, Decimal] | None:
    """Weekly hours before and after, from a sentence like "cut my hours from 40 to 30 a week"."""
    for text in texts:
        found = re.search(
            r"hours[^.]*?from\s+(\d+(?:\.\d+)?)\s+to\s+(\d+(?:\.\d+)?)", text, re.IGNORECASE
        )
        if found:
            before, after = Decimal(found.group(1)), Decimal(found.group(2))
            if before > 0:
                return before, after
    return None


def intent_key(text: str | None) -> str | None:
    """The application's free-text intent as keep or sell; None when it says neither."""
    lowered = (text or "").lower()
    if re.search(r"\b(keep|stay|remain)\b", lowered):
        return "keep"
    if re.search(r"\b(sell|short sale|leave)\b", lowered):
        return "sell"
    return None


def _evidence(document_id: UUID, field_name: str, lines: Sequence[str]) -> Evidence:
    return {"document_id": str(document_id), "field": field_name, "line_ids": list(lines)}


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


def _sum_working(parts: Sequence[Decimal], total: Decimal) -> str:
    if len(parts) == 1:
        return money(total)
    return f"{' + '.join(money(p) for p in parts)} = {money(total)}"


# --- the analysis ---------------------------------------------------------------------------


class _Budget:
    def __init__(self, inputs: BudgetInputs, cfg: AnalysisConfig) -> None:
        self.i = inputs
        self.t = cfg.thresholds
        self.version = cfg.calc_version("thresholds")
        self.calcs: list[Calc] = []
        self.flags: list[FlagResult] = []

    def flag(
        self, code: str, key: str, evidence: Sequence[Evidence] = (), **values: object
    ) -> None:
        severity, message = self.t.flag(code, **values)
        self.flags.append(FlagResult(code, key, severity, message, tuple(evidence)))

    def cannot(self, what: str, missing: str) -> None:
        self.flag("HB-I101", what, what=what, missing=missing)

    # -- the lines --

    def line_for(self, description: str) -> str:
        wanted = description.strip().lower()
        for category in self.t.budget_categories.value:
            if category.lower() == wanted:
                return category
        return OTHER if OTHER in self.t.budget_categories.value else description

    def stated_by_line(self) -> dict[str, list[StatedRow]]:
        out: dict[str, list[StatedRow]] = {}
        for row in self.i.stated_expenses:
            out.setdefault(self.line_for(row.description), []).append(row)
        return out

    def observed_for(self, category: str) -> tuple[Decimal, str, list[DebitLine]] | None:
        mapping = self.t.budget_category_map.value
        found = [d for d in self.i.debits if mapping.get(d.category) == category]
        if not found:
            return None
        newest = max((d.posted_on.year, d.posted_on.month) for d in found)
        month = [d for d in found if (d.posted_on.year, d.posted_on.month) == newest]
        month.sort(key=lambda d: (d.posted_on, d.line_ref))
        return sum((d.amount for d in month), Decimal(0)), month_label(*newest), month

    def lines(self) -> list[LineResult]:
        stated = self.stated_by_line()
        out: list[LineResult] = []
        have_stated, have_statements = bool(self.i.stated_expenses), self.i.has_statements
        for category in self.t.budget_categories.value:
            slug_ = slug(category)
            rows = stated.get(category, [])
            stated_calc = None
            stated_amount: Decimal | None = None
            if have_stated:
                stated_amount = sum((r.amount for r in rows), Decimal(0))
                what = "the application" if rows else "no line on the application"
                listed = [
                    r.description for r in rows if r.description.strip().lower() != category.lower()
                ]
                note = f" (includes {', '.join(listed)})" if listed else ""
                stated_calc = _calc(
                    f"stated_{slug_}",
                    stated_amount,
                    "usd",
                    "amount the borrower stated for this line",
                    {"stated": stated_amount},
                    f"{_sum_working([r.amount for r in rows], stated_amount) if rows else '0.00'}"
                    f" from {what}{note}",
                    self.version,
                    [_evidence(r.document_id, "monthly_expenses", r.lines) for r in rows],
                )
            observed_amount: Decimal | None = None
            observed_month: str | None = None
            observed_calc = None
            if have_statements:
                found = self.observed_for(category)
                if found is None:
                    observed_amount = Decimal("0.00")
                    working = "no debit in this line in the statements"
                    evidence: list[Evidence] = []
                else:
                    observed_amount, observed_month, debits = found
                    working = (
                        f"{month_name(observed_month)}: "
                        f"{_sum_working([d.amount for d in debits], observed_amount)}"
                    )
                    evidence = [
                        _evidence(d.document_id, "transaction", [d.line_ref]) for d in debits
                    ]
                observed_calc = _calc(
                    f"observed_{slug_}",
                    observed_amount,
                    "usd",
                    "debits in this line in the latest statement month that has one",
                    {"observed": observed_amount}
                    | ({"month": observed_month} if observed_month else {}),
                    working,
                    self.version,
                    evidence,
                )
            adjustment = self.i.adjustments.get(category)
            adjusted = adjustment[0] if adjustment else None
            effective = adjusted if adjusted is not None else observed_amount
            flagged = False
            if stated_amount is not None and effective is not None:
                difference = abs(stated_amount - effective)
                if difference > self.t.stated_vs_observed_tolerance(stated_amount, effective):
                    flagged = True
                    self.flag(
                        "HB-W101",
                        category,
                        [e for c in (stated_calc, observed_calc) if c for e in c.evidence[:1]],
                        category=category,
                        stated=money(stated_amount),
                        observed=money(effective),
                        difference=money(difference),
                    )
            out.append(
                LineResult(
                    category,
                    stated_amount,
                    observed_amount,
                    observed_month,
                    adjusted,
                    adjustment[1] if adjustment else None,
                    flagged,
                    stated_calc,
                    observed_calc,
                )
            )
        return out

    # -- income --

    def income(self) -> tuple[Decimal | None, Decimal | None]:
        stubs = sorted(self.i.stubs, key=lambda s: s.pay_date)
        if not stubs:
            self.cannot("documented income", "a pay stub with its gross and net pay")
            return None, None
        latest = stubs[-1]
        gross = monthly(latest.gross, latest.periods_per_year)
        net = monthly(latest.net, latest.periods_per_year)
        for name, amount, per_period, lines, field_name in (
            (
                "documented_gross_monthly_income",
                gross,
                latest.gross,
                latest.gross_lines,
                "gross_pay_current",
            ),
            ("documented_net_monthly_income", net, latest.net, latest.net_lines, "net_pay_current"),
        ):
            self.calcs.append(
                _calc(
                    name,
                    amount,
                    "usd",
                    "pay for the period on the latest stub x pay periods per year / 12",
                    {"per_period": per_period, "periods_per_year": str(latest.periods_per_year)},
                    f"{money(per_period)} x {latest.periods_per_year} / 12 = {money(amount)}",
                    self.version,
                    [_evidence(latest.document_id, field_name, lines)],
                )
            )
        return gross, net

    def income_change(self, gross: Decimal | None) -> Decimal | None:
        """The earliest documented gross monthly income, and the change since (a ratio)."""
        stubs = sorted(self.i.stubs, key=lambda s: s.pay_date)
        if gross is None or len(stubs) < 2 or stubs[0].pay_date == stubs[-1].pay_date:
            if gross is not None:
                self.cannot("the change in income", "two pay stubs from different pay dates")
            return None
        first = stubs[0]
        before = monthly(first.gross, first.periods_per_year)
        if before <= 0:
            return None
        ratio = six_places((gross - before) / before)
        self.calcs.append(
            _calc(
                "income_change",
                ratio,
                "ratio",
                "(latest gross monthly income - earliest gross monthly income) / earliest",
                {"latest": gross, "earliest": before},
                f"({money(gross)} - {money(before)}) / {money(before)} = {percent(ratio)}",
                self.version,
                [
                    _evidence(first.document_id, "gross_pay_current", first.gross_lines),
                    _evidence(stubs[-1].document_id, "gross_pay_current", stubs[-1].gross_lines),
                ],
            )
        )
        return before

    # -- measures --

    def totals(self, lines: list[LineResult]) -> tuple[Decimal | None, Decimal | None]:
        stated_total: Decimal | None = None
        observed_total: Decimal | None = None
        if self.i.stated_expenses:
            parts = [line.stated for line in lines if line.stated is not None]
            stated_total = sum(parts, Decimal(0))
            self.calcs.append(
                _calc(
                    "stated_expenses_total",
                    stated_total,
                    "usd",
                    "sum of the stated amounts of every budget line",
                    {line.category: line.stated for line in lines if line.stated is not None},
                    _sum_working([p for p in parts if p != 0] or parts, stated_total),
                    self.version,
                    [
                        e
                        for line in lines
                        if line.stated_calc
                        for e in line.stated_calc.evidence[:1]
                    ],
                )
            )
        else:
            self.cannot("stated expenses", "the application's monthly expenses")
        if self.i.has_statements:
            parts = [
                line.effective_observed for line in lines if line.effective_observed is not None
            ]
            observed_total = sum(parts, Decimal(0))
            adjusted = [line.category for line in lines if line.adjusted is not None]
            self.calcs.append(
                _calc(
                    "observed_expenses_total",
                    observed_total,
                    "usd",
                    "sum of the observed amounts of every line (a person's adjustment counts)",
                    {
                        line.category: line.effective_observed
                        for line in lines
                        if line.effective_observed is not None
                    },
                    _sum_working([p for p in parts if p != 0] or parts, observed_total)
                    + (f" (adjusted: {', '.join(adjusted)})" if adjusted else ""),
                    self.version,
                    [
                        e
                        for line in lines
                        if line.observed_calc
                        for e in line.observed_calc.evidence[:1]
                    ],
                )
            )
        else:
            self.cannot("observed expenses", "a bank statement")
        return stated_total, observed_total

    def surplus(self, net: Decimal | None, name: str, expenses: Decimal | None, basis: str) -> None:
        if net is None or expenses is None:
            return
        value = net - expenses
        self.calcs.append(
            _calc(
                name,
                value,
                "usd",
                f"documented net monthly income - {basis} expenses",
                {"net_monthly_income": net, "expenses": expenses},
                f"{money(net)} - {money(expenses)} = {money(value)}",
                self.version,
            )
        )

    def housing(self, gross: Decimal | None, before: Decimal | None) -> None:
        payment = self.i.contractual_payment
        if payment is None:
            self.cannot("the housing ratio", "the mortgage statement's regular payment")
            return
        evidence = [_evidence(payment.document_id, "regular_monthly_payment", payment.lines)]
        for name, income, label in (
            ("housing_ratio", gross, "documented gross monthly income"),
            ("housing_ratio_before_cut", before, "gross monthly income before the change"),
        ):
            if income is None or income <= 0:
                continue
            ratio = six_places(payment.value / income)
            self.calcs.append(
                _calc(
                    name,
                    ratio,
                    "ratio",
                    f"contractual payment / {label}",
                    {"contractual_payment": payment.value, "gross_monthly_income": income},
                    f"{money(payment.value)} / {money(income)} = {percent(ratio)}",
                    self.version,
                    evidence,
                )
            )

    def arrears_and_assets(self) -> None:
        arrears = self.i.arrears
        if arrears is None:
            self.cannot("arrears", "the mortgage statement's past due amount")
        else:
            self.calcs.append(
                _calc(
                    "arrears",
                    arrears.value,
                    "usd",
                    "past due amount on the mortgage statement",
                    {"past_due_amount": arrears.value},
                    money(arrears.value),
                    self.version,
                    [_evidence(arrears.document_id, "past_due_amount", arrears.lines)],
                )
            )
        if not self.i.balances:
            self.cannot("liquid assets", "a bank statement's closing balance")
            return
        total = sum((b.closing for b in self.i.balances), Decimal(0))
        self.calcs.append(
            _calc(
                "liquid_assets",
                total,
                "usd",
                "sum of the latest closing balance of each account",
                {f"account_{b.account_last4 or 'unknown'}": b.closing for b in self.i.balances},
                _sum_working([b.closing for b in self.i.balances], total),
                self.version,
                [_evidence(b.document_id, "closing_balance", b.lines) for b in self.i.balances],
            )
        )
        if arrears is not None and arrears.value > 0:
            share = six_places(total / arrears.value)
            self.calcs.append(
                _calc(
                    "liquid_assets_share_of_arrears",
                    share,
                    "ratio",
                    "liquid assets / arrears",
                    {"liquid_assets": total, "arrears": arrears.value},
                    f"{money(total)} / {money(arrears.value)} = {percent(share)}",
                    self.version,
                    [_evidence(arrears.document_id, "past_due_amount", arrears.lines)],
                )
            )

    # -- consistency checks --

    def check(
        self, name: str, agrees: bool, formula: str, inputs: Mapping[str, str], working: str
    ) -> None:
        """A comparison shown with both values. 1 when they agree, 0 when they differ."""
        self.calcs.append(
            _calc(name, Decimal(int(agrees)), "match", formula, inputs, working, self.version)
        )

    def checks(self, gross: Decimal | None, before: Decimal | None) -> None:
        self.income_check(gross)
        letter = self.i.letter
        if letter is None:
            return
        self.hours_check(gross, before, letter)
        self.reason_check(letter)
        self.intent_check(letter)

    def income_check(self, gross: Decimal | None) -> None:
        if gross is None or not self.i.stated_income:
            return
        stated = sum((r.amount for r in self.i.stated_income), Decimal(0))
        difference = abs(stated - gross)
        agrees = difference <= self.t.stated_vs_observed_tolerance(stated, gross)
        self.check(
            "check_income_stated_vs_documented",
            agrees,
            "stated monthly income against documented gross monthly income",
            {"stated": plain(stated), "documented": plain(gross)},
            f"Stated {money(stated)}; documented {money(gross)}. "
            + ("They agree." if agrees else f"They differ by {money(difference)}."),
        )
        if not agrees:
            self.flag(
                "HB-W105",
                "income",
                stated=money(stated),
                documented=money(gross),
                difference=money(difference),
            )

    def hours_check(
        self, gross: Decimal | None, before: Decimal | None, letter: LetterFacts
    ) -> None:
        change = next((c for c in self.calcs if c.name == "income_change"), None)
        if letter.hours is None or change is None or gross is None or before is None:
            return
        old, new = letter.hours
        hours = six_places((new - old) / old)
        pay = change.value
        points = abs(pay - hours) * HUNDRED
        agrees = points <= self.t.pay_vs_hours_points.value
        self.check(
            "check_pay_vs_hours",
            agrees,
            "change in pay on the stubs against the change in hours in the letter",
            {"pay_change": plain(pay), "hours_change": plain(hours)},
            f"Pay on the stubs changed by {percent(pay)} "
            f"({money(before)} to {money(gross)} a month); the letter says hours changed by "
            f"{percent(hours)} ({plain(old)} to {plain(new)} a week). "
            + (
                "They agree."
                if agrees
                else f"They differ by {points.quantize(Decimal('0.01'))} points."
            ),
        )
        if not agrees:
            self.flag("HB-W102", "hours", pay_change=percent(pay), hours_change=percent(hours))

    def reason_check(self, letter: LetterFacts) -> None:
        keys = {
            self.i.reason_keys[r.strip().lower()]
            for r in self.i.application_reasons
            if r.strip().lower() in self.i.reason_keys
        }
        if not keys or letter.primary_reason is None:
            return
        agrees = letter.primary_reason in keys
        printed = ", ".join(self.i.application_reasons)
        self.check(
            "check_reason_vs_letter",
            agrees,
            "reasons ticked on the application against the letter's main reason",
            {"application": printed, "letter": letter.primary_reason},
            f"The application ticks {printed}; "
            f"the letter's main reason is {letter.primary_reason}. "
            + ("They agree." if agrees else "They differ."),
        )
        if not agrees:
            self.flag("HB-W103", "reason", application=printed, letter=letter.primary_reason)

    def intent_check(self, letter: LetterFacts) -> None:
        stated = intent_key(self.i.application_intent)
        if stated is None or letter.intent is None:
            return
        agrees = stated == letter.intent
        self.check(
            "check_intent_vs_letter",
            agrees,
            "intent on the application against the intent in the letter",
            {"application": stated, "letter": letter.intent},
            f"The application says {stated}; the letter says {letter.intent}. "
            + ("They agree." if agrees else "They differ."),
        )
        if not agrees:
            self.flag("HB-W104", "intent", application=stated, letter=letter.intent)

    def run(self) -> BudgetOutcome:
        gross, net = self.income()
        before = self.income_change(gross)
        lines = self.lines()
        stated_total, observed_total = self.totals(lines)
        self.surplus(net, "surplus_stated", stated_total, "stated")
        self.surplus(net, "surplus_observed", observed_total, "observed")
        self.housing(gross, before)
        self.arrears_and_assets()
        self.checks(gross, before)
        return BudgetOutcome(lines, self.calcs, self.flags)


def compute_budget(inputs: BudgetInputs, cfg: AnalysisConfig) -> BudgetOutcome:
    """The budget lines and measures from the case's documents. Pure: the same inputs and settings
    always give the same result."""
    return _Budget(inputs, cfg).run()

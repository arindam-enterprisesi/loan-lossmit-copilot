"""Credit report analysis (Feature Design 4): every metric in code, with working and evidence.

Pure ``Decimal`` and ``date`` arithmetic over what the reader extracted from the sample credit
report: no database, no model, no clock. The report is simulated; no bureau is contacted and no
credit decision is made (rule 3: this says what the report shows and flags it for a person to look
at). Every figure is a ``Calc`` carrying its working and the report lines it came from (rules 1
and 2); every setting comes from ``thresholds.yaml``, labelled illustrative (rule 4).

What it computes (Feature Design 4.5): the representative score (the middle of three, the lower of
two), utilization per revolving account and in total, late payments by severity within the lookback
and the months since the last one, inquiries matched to a new account, the derogatory list,
and the monthly payments by account type that Feature 3 uses. The summary is a template filled from
those results.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from uuid import UUID

from app.services.analysis_config import AnalysisConfig
from app.services.calculations import (
    Calc,
    Evidence,
    money,
    percent,
    plain,
    six_places,
)

REVOLVING = "revolving"
# Words a creditor's name shares with many others; they never decide that two names match.
GENERIC_WORDS = frozenset(
    {"card", "cards", "bank", "finance", "financial", "services", "servicing", "loan", "loans"}
    | {"mortgage", "auto", "student", "rewards", "visa", "mastercard", "credit", "retail", "co"}
)
# Tradeline statuses that make an account derogatory whatever its late counts.
DEROGATORY_STATUSES = ("charge", "collection", "repossess", "foreclos", "bankrupt", "default")
SEVERITIES = (("late_30", "30-day"), ("late_60", "60-day"), ("late_90", "90-day"))


# --- what is read ----------------------------------------------------------------------------


@dataclass(frozen=True)
class ScoreIn:
    bureau: str
    value: int
    lines: tuple[str, ...] = ()


@dataclass(frozen=True)
class TradelineIn:
    number: int  # the row number in the report, 1 first
    creditor: str
    account_type: str
    ownership: str | None = None
    opened_on: date | None = None
    status: str | None = None
    balance: Decimal | None = None
    credit_limit: Decimal | None = None
    monthly_payment: Decimal | None = None
    past_due: Decimal | None = None
    late_30: int = 0
    late_60: int = 0
    late_90: int = 0
    last_late_on: date | None = None
    remarks: str = ""
    lines: tuple[str, ...] = ()


@dataclass(frozen=True)
class InquiryIn:
    number: int
    creditor: str
    on: date | None
    lines: tuple[str, ...] = ()


@dataclass(frozen=True)
class CreditInputs:
    document_id: UUID | None = None
    report_date: date | None = None
    scores: tuple[ScoreIn, ...] = ()
    tradelines: tuple[TradelineIn, ...] = ()
    inquiries: tuple[InquiryIn, ...] = ()
    # Fraud alerts, freezes and consumer statements: always shown first.
    alerts: tuple[str, ...] = ()
    alert_lines: tuple[str, ...] = ()
    # What the report lists as collections and public records (a count and the lines).
    collections: int = 0
    public_records: int = 0


# --- what is returned ------------------------------------------------------------------------


@dataclass(frozen=True)
class FoundFlag:
    code: str
    severity: str
    message: str
    key: str  # tells two flags of one code apart
    evidence: tuple[Evidence, ...] = ()


@dataclass(frozen=True)
class TradelineResult:
    tradeline: TradelineIn
    utilization: Calc | None
    utilization_over_review_level: bool
    months_since_last_late: Calc | None
    late_in_lookback: bool
    derogatory: bool


@dataclass(frozen=True)
class InquiryResult:
    inquiry: InquiryIn
    in_window: bool
    matched: TradelineIn | None


@dataclass(frozen=True)
class CreditOutcome:
    representative: Calc | None
    representative_bureau: str | None
    method: str
    tradelines: list[TradelineResult]
    inquiries: list[InquiryResult]
    calcs: list[Calc]
    flags: list[FoundFlag]
    derogatory: list[TradelineIn]
    summary: list[str]
    summary_facts: SummaryFacts
    notes: list[str] = field(default_factory=list)


# --- helpers ---------------------------------------------------------------------------------


def months_between(earlier: date, later: date) -> int:
    """Whole months from ``earlier`` to ``later``: 2025-03-05 to 2026-10-12 is 19."""
    months = (later.year - earlier.year) * 12 + (later.month - earlier.month)
    return months - 1 if later.day < earlier.day else months


def slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")


def _words(name: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9]+", name.lower()) if w not in GENERIC_WORDS}


def same_creditor(a: str, b: str) -> bool:
    """Two creditor names that share a distinctive word ("Harbor Retail", "Harbor Retail Card")."""
    return bool(_words(a) & _words(b))


def _evidence(document_id: UUID | None, field_name: str, lines: Sequence[str]) -> Evidence:
    return {
        "document_id": str(document_id) if document_id else None,
        "field": field_name,
        "line_ids": list(lines),
    }


def _ordinal(count: int) -> str:
    return {1: "One", 2: "Two", 3: "Three"}.get(count, str(count))


@dataclass(frozen=True)
class LateFact:
    creditor: str
    severity: str  # "30-day", "60-day" or "90-day": the worst the account shows
    count: int
    months_before_report: int


@dataclass(frozen=True)
class SummaryFacts:
    """What the template summary is filled from: the results, not the report."""

    alerts: tuple[str, ...] = ()
    late: tuple[LateFact, ...] = ()
    over_review_level: tuple[tuple[str, str], ...] = ()  # (creditor, utilization shown)
    inquiries: tuple[tuple[str, str | None], ...] = ()  # (creditor, matched account) in the window
    derogatory: tuple[str, ...] = ()


def severity_label(line: TradelineIn) -> str:
    counts = [(label, getattr(line, attr)) for attr, label in SEVERITIES]
    return next((label for label, n in reversed(counts) if n), "late")


def summarize(facts: SummaryFacts) -> list[str]:
    """The credit summary: a template filled from the results (Feature Design 4.5)."""
    lines: list[str] = []
    if facts.alerts:
        lines.append(f"Alerts on the report: {'; '.join(facts.alerts)}.")
    for item in facts.late:
        payments = "payment" if item.count == 1 else "payments"
        lines.append(
            f"{_ordinal(item.count)} {item.severity} late {payments} on {item.creditor}, "
            f"{item.months_before_report} months before the report date."
        )
    if not facts.late:
        lines.append("No late payments within the lookback.")
    for creditor, shown in facts.over_review_level:
        lines.append(f"{creditor} utilization is {shown}, above the review level.")
    for creditor, matched in facts.inquiries:
        if matched:
            lines.append(f"The {creditor} inquiry matches the new account {matched}.")
        else:
            lines.append(f"The {creditor} inquiry has no matching account.")
    for creditor in facts.derogatory:
        lines.append(f"{creditor} is listed as derogatory.")
    return lines


class _Analysis:
    def __init__(self, inputs: CreditInputs, cfg: AnalysisConfig) -> None:
        self.i = inputs
        self.t = cfg.thresholds
        self.version = cfg.calc_version("thresholds")
        self.calcs: list[Calc] = []
        self.flags: list[FoundFlag] = []
        self.notes: list[str] = []

    def calc(
        self,
        name: str,
        value: Decimal,
        unit: str,
        formula: str,
        inputs: dict[str, str],
        working: str,
        evidence: Sequence[Evidence] = (),
    ) -> Calc:
        found = Calc(
            name=name,
            value=value,
            unit=unit,
            formula=formula,
            inputs=inputs,
            working=working,
            config_version=self.version,
            evidence=tuple(evidence),
        )
        self.calcs.append(found)
        return found

    def flag(
        self, code: str, key: str, evidence: Sequence[Evidence] = (), **values: object
    ) -> None:
        severity, message = self.t.flag(code, **values)
        self.flags.append(FoundFlag(code, severity, message, key, tuple(evidence)))

    def cannot(self, what: str, missing: str) -> None:
        self.notes.append(f"Cannot compute {what}: {missing} not found.")
        self.flag("CR-I101", slug(what), what=what, missing=missing)

    # -- scores --

    def representative(self) -> tuple[Calc | None, str | None]:
        scores = self.i.scores
        if not scores:
            self.cannot("the representative score", "a score on the report")
            return None, None
        ranked = sorted(scores, key=lambda s: (s.value, s.bureau))
        if len(ranked) >= 3:
            chosen, how = ranked[len(ranked) // 2], "the middle of the scores"
        else:
            chosen, how = ranked[0], "the lower of two scores" if len(ranked) == 2 else "the score"
        listed = ", ".join(str(s.value) for s in scores)
        found = self.calc(
            "representative_score",
            Decimal(chosen.value),
            "score",
            "middle of three scores, the lower of two",
            {s.bureau: str(s.value) for s in scores},
            f"Scores {listed}: {how} is {chosen.value}",
            [_evidence(self.i.document_id, "scores", chosen.lines)],
        )
        return found, chosen.bureau

    # -- tradelines --

    def utilization(self, line: TradelineIn) -> tuple[Calc | None, bool]:
        if line.account_type != REVOLVING or line.credit_limit is None or line.balance is None:
            return None, False
        if line.credit_limit <= 0:
            return None, False
        ratio = six_places(line.balance / line.credit_limit)
        level = self.t.credit_utilization_review_level.value
        over = ratio > level
        found = self.calc(
            f"utilization_{slug(line.creditor)}",
            ratio,
            "ratio",
            "balance / credit limit",
            {"balance": plain(line.balance), "credit_limit": plain(line.credit_limit)},
            f"{money(line.balance)} / {money(line.credit_limit)} = {percent(ratio)}",
            [_evidence(self.i.document_id, f"tradeline_{line.number:03d}", line.lines)],
        )
        if over:
            self.flag(
                "CR-W101",
                slug(line.creditor),
                [found.evidence[0]],
                creditor=line.creditor,
                utilization=percent(ratio),
                level=percent(level),
            )
        return found, over

    def late(self, line: TradelineIn) -> tuple[Calc | None, bool]:
        counts = [(label, getattr(line, attr)) for attr, label in SEVERITIES]
        total = sum(n for _, n in counts)
        if total == 0 and line.last_late_on is None:
            return None, False
        report = self.i.report_date
        if line.last_late_on is None or report is None:
            if total:
                missing = "the date of the last late payment" if report else "the report date"
                self.cannot(f"months since the last late payment on {line.creditor}", missing)
            return None, False
        months = months_between(line.last_late_on, report)
        lookback = self.t.credit_late_lookback_months.value
        within = 0 <= months <= lookback
        found = self.calc(
            f"months_since_last_late_{slug(line.creditor)}",
            Decimal(months),
            "months",
            "whole months from the most recent late payment to the report date",
            {"last_late_on": line.last_late_on.isoformat(), "report_date": report.isoformat()},
            f"{line.last_late_on.isoformat()} to {report.isoformat()} = {months} months",
            [_evidence(self.i.document_id, f"tradeline_{line.number:03d}", line.lines)],
        )
        if within:
            worst = next(label for label, n in reversed(counts) if n)
            self.flag(
                "CR-W102",
                slug(line.creditor),
                [found.evidence[0]],
                creditor=line.creditor,
                severity=worst,
                months=months,
                lookback=lookback,
            )
        return found, within

    def derogatory(self, line: TradelineIn) -> bool:
        status = (line.status or "").lower()
        bad = any(word in status for word in DEROGATORY_STATUSES) or bool(
            line.past_due and line.past_due > 0
        )
        if line.past_due and line.past_due > 0:
            self.flag(
                "CR-W104",
                slug(line.creditor),
                [_evidence(self.i.document_id, f"tradeline_{line.number:03d}", line.lines)],
                creditor=line.creditor,
                past_due=money(line.past_due),
            )
        return bad

    # -- totals --

    def total_utilization(self) -> None:
        revolving = [
            t
            for t in self.i.tradelines
            if t.account_type == REVOLVING
            and t.balance is not None
            and t.credit_limit is not None
            and t.credit_limit > 0
        ]
        if not revolving:
            return
        balance = sum((t.balance or Decimal(0) for t in revolving), Decimal(0))
        limit = sum((t.credit_limit or Decimal(0) for t in revolving), Decimal(0))
        ratio = six_places(balance / limit)
        self.calc(
            "total_revolving_utilization",
            ratio,
            "ratio",
            "total revolving balances / total revolving limits",
            {"balances": plain(balance), "limits": plain(limit)},
            f"{money(balance)} / {money(limit)} = {percent(ratio)}",
            [
                _evidence(self.i.document_id, f"tradeline_{t.number:03d}", t.lines)
                for t in revolving
            ],
        )

    def payments(self) -> None:
        paying = [t for t in self.i.tradelines if t.monthly_payment is not None]
        if not paying:
            if self.i.tradelines:
                self.cannot("the monthly payments", "a monthly payment on any account")
            return
        by_type: dict[str, list[TradelineIn]] = {}
        for t in paying:
            by_type.setdefault(t.account_type or "other", []).append(t)
        for kind, lines in sorted(by_type.items()):
            parts = [t.monthly_payment or Decimal(0) for t in lines]
            total = sum(parts, Decimal(0))
            self.calc(
                f"monthly_payments_{slug(kind)}",
                total,
                "usd",
                f"sum of the monthly payments on {kind} accounts",
                {t.creditor: plain(t.monthly_payment or Decimal(0)) for t in lines},
                f"{' + '.join(money(p) for p in parts)} = {money(total)}"
                if len(parts) > 1
                else money(total),
                [
                    _evidence(self.i.document_id, f"tradeline_{t.number:03d}", t.lines)
                    for t in lines
                ],
            )
        everything = [t.monthly_payment or Decimal(0) for t in paying]
        total = sum(everything, Decimal(0))
        self.calc(
            "monthly_payments_total",
            total,
            "usd",
            "sum of the monthly payments on every account",
            {t.creditor: plain(t.monthly_payment or Decimal(0)) for t in paying},
            f"{' + '.join(money(p) for p in everything)} = {money(total)}"
            if len(everything) > 1
            else money(total),
            [_evidence(self.i.document_id, f"tradeline_{t.number:03d}", t.lines) for t in paying],
        )

    # -- inquiries --

    def inquiries(self) -> list[InquiryResult]:
        report = self.i.report_date
        window = self.t.credit_inquiry_window_days.value
        match_days = self.t.credit_inquiry_match_days.value
        out: list[InquiryResult] = []
        for inquiry in self.i.inquiries:
            if inquiry.on is None or report is None:
                out.append(InquiryResult(inquiry, False, None))
                continue
            age = (report - inquiry.on).days
            in_window = 0 <= age <= window
            matched: TradelineIn | None = None
            for line in self.i.tradelines:
                if (
                    line.opened_on is not None
                    and abs((line.opened_on - inquiry.on).days) <= match_days
                    and same_creditor(inquiry.creditor, line.creditor)
                ):
                    matched = line
                    break
            evidence = _evidence(self.i.document_id, f"inquiry_{inquiry.number:03d}", inquiry.lines)
            if in_window and matched is None:
                self.flag(
                    "CR-W103",
                    slug(inquiry.creditor),
                    [evidence],
                    creditor=inquiry.creditor,
                    date=inquiry.on.isoformat(),
                    days=match_days,
                )
            elif in_window and matched is not None:
                self.flag(
                    "CR-I102",
                    slug(inquiry.creditor),
                    [
                        evidence,
                        _evidence(
                            self.i.document_id, f"tradeline_{matched.number:03d}", matched.lines
                        ),
                    ],
                    creditor=inquiry.creditor,
                    date=inquiry.on.isoformat(),
                    account=matched.creditor,
                    opened=(matched.opened_on or inquiry.on).isoformat(),
                )
            out.append(InquiryResult(inquiry, in_window, matched))
        return out

    # -- alerts and the template summary --

    def alerts(self) -> None:
        if self.i.alerts:
            self.flag(
                "CR-W105",
                "alerts",
                [_evidence(self.i.document_id, "alerts", self.i.alert_lines)],
                alerts="; ".join(self.i.alerts),
            )

    def summary_facts(
        self,
        results: list[TradelineResult],
        found: list[InquiryResult],
        derogatory: list[TradelineIn],
    ) -> SummaryFacts:
        late = tuple(
            LateFact(
                r.tradeline.creditor,
                severity_label(r.tradeline),
                sum(getattr(r.tradeline, attr) for attr, _ in SEVERITIES),
                int(r.months_since_last_late.value),
            )
            for r in results
            if r.late_in_lookback and r.months_since_last_late is not None
        )
        over = tuple(
            (r.tradeline.creditor, percent(r.utilization.value))
            for r in results
            if r.utilization_over_review_level and r.utilization is not None
        )
        inquiries = tuple(
            (i.inquiry.creditor, i.matched.creditor if i.matched else None)
            for i in found
            if i.in_window
        )
        return SummaryFacts(
            self.i.alerts, late, over, inquiries, tuple(t.creditor for t in derogatory)
        )


def analyze(inputs: CreditInputs, cfg: AnalysisConfig) -> CreditOutcome:
    """Compute every metric and flag of a credit report. The same report and settings always give
    the same result."""
    run = _Analysis(inputs, cfg)
    if not inputs.tradelines and not inputs.scores and not inputs.inquiries:
        run.cannot("the credit analysis", "a credit report with scores or accounts")
    representative, bureau = run.representative() if inputs.scores else (None, None)
    results: list[TradelineResult] = []
    derogatory: list[TradelineIn] = []
    for line in inputs.tradelines:
        utilization, over = run.utilization(line)
        months, within = run.late(line)
        bad = run.derogatory(line)
        if bad:
            derogatory.append(line)
        results.append(TradelineResult(line, utilization, over, months, within, bad))
    run.total_utilization()
    run.payments()
    found = run.inquiries()
    run.alerts()
    facts = run.summary_facts(results, found, derogatory)
    return CreditOutcome(
        representative=representative,
        representative_bureau=bureau,
        method=cfg.thresholds.credit_score_method.value,
        tradelines=results,
        inquiries=found,
        calcs=run.calcs,
        flags=run.flags,
        derogatory=derogatory,
        summary=summarize(facts),
        summary_facts=facts,
        notes=run.notes,
    )


__all__ = [
    "CreditInputs",
    "CreditOutcome",
    "InquiryIn",
    "InquiryResult",
    "LateFact",
    "ScoreIn",
    "SummaryFacts",
    "TradelineIn",
    "TradelineResult",
    "analyze",
    "months_between",
    "summarize",
]

"""Checks that run in code on an extracted document (FSD 4.3 and 4.4), never in a model.

Input is plain data (the extracted fields, the document's numbered lines and its pages); output is
a list of findings, each with its rule code (``DI-CHK-02``), a template message, the lines that are
its evidence, and the working of the calculation (CLAUDE.md rules 1 and 2). This module touches no
database: ``app.services.flags`` turns findings into flag rows.

Checks, by document type (codes from the FSD):
  every field   a cited line must exist and the value must really appear in it (DI-W601), a value
                must be readable as its kind (DI-W605), a required field must be present (DI-W604)
  pay stub      DI-CHK-01 earnings add up to gross, 02 gross minus deductions is net,
                03 period start is not after its end, 04 year to date is not below current
  bank          DI-CHK-05 opening plus transactions is closing, 06 printed totals match the
                transactions, 07 running balances agree, 08 transactions fall inside the period
  every type    DI-W701 printed "Page X of Y" against the pages uploaded, and "continued" signs
A check that is missing an input says so ("cannot check") instead of passing quietly.

There is at most one finding per entity and code, matching the unique constraint on ``flags``.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from dataclasses import field as dataclass_field
from datetime import date as Date
from decimal import Decimal
from typing import Any, Literal

from app.services.doc_lines import PAGE_LABEL
from app.services.document_config import DocumentFieldsConfig, ValidationConfig
from app.services.normalize import display_amount, parse_amount, parse_date

_AMOUNT_TOKEN = re.compile(r"(?<![\w.])\(?-?\$?\d[\d,]*(?:\.\d+)?\)?(?!\w)")
_DATE_TOKENS = (
    re.compile(r"\d{4}-\d{2}-\d{2}"),
    re.compile(r"\d{1,2}/\d{1,2}/\d{2,4}"),
    re.compile(r"[A-Za-z]{3,9}\.? \d{1,2}, \d{4}"),
    re.compile(r"\d{1,2} [A-Za-z]{3,9}\.? \d{4}"),
)
_KIND_WORDS = {
    "amount": "an amount",
    "date": "a date",
    "id_last4": "an ID number",
    "number": "a number",
}
REVIEWED = ("confirmed", "corrected")  # review statuses that mean a person checked the value
_ZERO = Decimal("0.00")


# --- input and output -----------------------------------------------------------------------


@dataclass(frozen=True)
class FieldInput:
    name: str
    value: str | None  # the text as read, or as a person corrected it
    normalized: str | None  # the standard form of ``value``; None if missing or unreadable
    kind: str  # amount | date | text | id_last4
    lines: tuple[str, ...]  # cited line refs, such as "p1-L31"
    certainty: str  # what the reader said: high | medium | low
    review_status: str  # unreviewed | confirmed | corrected | rejected
    required: bool = False

    @property
    def present(self) -> bool:
        """A rejected value counts as missing, so downstream checks never use it."""
        return bool(self.value and self.value.strip()) and self.review_status != "rejected"


@dataclass(frozen=True)
class LineInput:
    ref: str
    text: str
    confidence: float | None = None  # None for the text layer


@dataclass(frozen=True)
class PageInput:
    page_no: int
    printed_label: str | None = None  # the "Page 1 of 3" printed on the page, if any


@dataclass(frozen=True)
class ValidationInput:
    doc_type: str
    fields: Mapping[str, FieldInput]
    lines: Mapping[str, LineInput]
    pages: Sequence[PageInput]
    signals: Sequence[str] = ()  # the reader's signs that the document is incomplete


@dataclass(frozen=True)
class Finding:
    code: str
    severity: str  # error | warning | info
    message: str
    entity: Literal["document", "field"]
    field: str | None  # the field flagged, when entity is "field"
    lines: tuple[str, ...]  # the evidence: line refs
    working: dict[str, Any] = dataclass_field(default_factory=dict)

    @property
    def marks_review(self) -> bool:
        """An info finding ("cannot check") does not put a field in front of a reviewer."""
        return self.severity != "info"


@dataclass(frozen=True)
class ValidationReport:
    findings: tuple[Finding, ...]
    certainty: dict[str, str]  # the final certainty of every field (FSD 4.4)
    found: dict[str, bool]  # whether each present field's value appears in its cited lines


# --- value-in-lines -------------------------------------------------------------------------


def _amount_in(text: str, wanted: Decimal, *, ignore_sign: bool = False) -> bool:
    if ignore_sign:
        wanted = abs(wanted)
    for tok in _AMOUNT_TOKEN.finditer(text):
        found = parse_amount(tok.group())
        if found is not None and (abs(found) if ignore_sign else found) == wanted:
            return True
    return False


def _date_in(text: str, wanted: str) -> bool:
    for pattern in _DATE_TOKENS:
        for tok in pattern.finditer(text):
            found = parse_date(tok.group())
            if found is not None and found.isoformat() == wanted:
                return True
    return False


def value_in_lines(
    kind: str, normalized: str, texts: Sequence[str], *, ignore_sign: bool = False
) -> bool:
    """Does the (normalised) value really appear in the cited lines?

    ``ignore_sign`` is for an amount printed in a deposit or withdrawal column: the page shows it
    unsigned and its sign comes from the column heading, so only the digits can be compared.
    """
    if not texts:
        return False
    if kind == "amount":
        wanted = parse_amount(normalized)
        return wanted is not None and any(
            _amount_in(t, wanted, ignore_sign=ignore_sign) for t in texts
        )
    if kind == "date":
        return any(_date_in(t, normalized) for t in texts)
    if kind == "id_last4":
        return any(normalized in re.sub(r"\D", "", t) for t in texts)
    squashed = " ".join(" ".join(texts).lower().split())
    return " ".join(normalized.lower().split()) in squashed


# --- the checks -----------------------------------------------------------------------------


class _Checks:
    def __init__(self, inp: ValidationInput, rules: ValidationConfig, cfg: DocumentFieldsConfig):
        self.inp, self.rules, self.cfg = inp, rules, cfg
        self.tol = rules.arithmetic_tolerance
        self.min_conf = float(rules.min_line_confidence)  # compared with an OCR score
        self.findings: list[Finding] = []
        self.found: dict[str, bool] = {}
        self._cannot: dict[str, tuple[str, list[str]]] = {}

    # lookups ---------------------------------------------------------------------------------

    def role(self, role: str) -> str | None:
        return self.cfg.role(self.inp.doc_type, role)

    def field(self, name: str | None) -> FieldInput | None:
        return self.inp.fields.get(name) if name else None

    def amount(self, name: str | None) -> Decimal | None:
        f = self.field(name)
        return parse_amount(f.normalized) if f and f.present and f.kind == "amount" else None

    def date(self, name: str | None) -> Date | None:
        f = self.field(name)
        return parse_date(f.normalized) if f and f.present and f.kind == "date" else None

    def cited(self, *names: str | None) -> tuple[str, ...]:
        refs: list[str] = []
        for name in names:
            f = self.field(name)
            for ref in f.lines if f else ():
                if ref not in refs:
                    refs.append(ref)
        return tuple(refs)

    def label(self, name: str | None) -> str:
        return self.cfg.field_label(self.inp.doc_type, name) if name else ""

    def missing(self, getter: Callable[[str | None], object], *names: str | None) -> list[str]:
        return [self.label(n) for n in names if n and getter(n) is None]

    # output ----------------------------------------------------------------------------------

    def emit(
        self,
        code: str,
        entity: Literal["document", "field"],
        field_name: str | None,
        lines: tuple[str, ...],
        working: dict[str, Any] | None = None,
        *,
        template: str | None = None,
        **values: object,
    ) -> None:
        severity, message = self.rules.flag(template or code, **values)
        self.findings.append(
            Finding(code, severity, message, entity, field_name, lines, working or {})
        )

    def cannot_check(self, code: str, rule: str, missing: list[str]) -> None:
        """Record that a check could not run. Several inputs of one check become one finding."""
        known_rule, names = self._cannot.setdefault(code, (rule, []))
        names.extend(m for m in missing if m not in names)
        self._cannot[code] = (known_rule, names)

    def flush_cannot_checks(self) -> None:
        for code, (rule, names) in self._cannot.items():
            severity, message = self.rules.flag("cannot_check", rule=rule, missing=", ".join(names))
            self.findings.append(
                Finding(code, severity, message, "document", None, (), {"missing": names})
            )

    # every field -----------------------------------------------------------------------------

    def check_fields(self) -> None:
        for name, f in self.inp.fields.items():
            if not f.present:
                if f.required:
                    self.emit("DI-W604", "field", name, (), label=self.label(name))
                continue
            if f.normalized is None:
                kind = _KIND_WORDS.get(f.kind, f.kind)
                self.emit("DI-W605", "field", name, f.lines, label=self.label(name), kind=kind)
                self.found[name] = False
                continue
            if f.review_status in REVIEWED:
                # A person has looked at it: a typed correction need not appear in the cited lines.
                self.found[name] = True
                continue
            texts = [self.inp.lines[r].text for r in f.lines if r in self.inp.lines]
            found = (
                bool(f.lines)
                and all(r in self.inp.lines for r in f.lines)
                and value_in_lines(
                    f.kind,
                    f.normalized,
                    texts,
                    ignore_sign=self.cfg.is_column_signed(self.inp.doc_type, name),
                )
            )
            self.found[name] = found
            if not found:
                self.emit("DI-W601", "field", name, f.lines)

    # pay stub --------------------------------------------------------------------------------

    def check_pay_stub(self) -> None:
        gross_n, net_n = self.role("gross"), self.role("net")
        ded_n, ytd_n = self.role("deductions"), self.role("ytd_gross")
        start_n, end_n = self.role("period_start"), self.role("period_end")
        gross, net, deductions, ytd = (self.amount(n) for n in (gross_n, net_n, ded_n, ytd_n))

        start, end = self.date(start_n), self.date(end_n)  # DI-CHK-03
        if start is None or end is None:
            self.cannot_check(
                "DI-CHK-03", "the pay period dates", self.missing(self.date, start_n, end_n)
            )
        elif start > end:
            self.emit(
                "DI-CHK-03",
                "field",
                start_n,
                self.cited(start_n, end_n),
                {"start": start.isoformat(), "end": end.isoformat()},
                start=start.isoformat(),
                end=end.isoformat(),
            )

        earnings = [
            (name, amt)
            for name in self.inp.fields
            if self.cfg.is_earnings_field(self.inp.doc_type, name)
            and (amt := self.amount(name)) is not None
        ]
        if gross is None or not earnings:  # DI-CHK-01
            lacking = self.missing(self.amount, gross_n) + ([] if earnings else ["earnings lines"])
            self.cannot_check("DI-CHK-01", "that earnings add up to gross pay", lacking)
        else:
            total = sum((a for _, a in earnings), _ZERO)
            if abs(total - gross) > self.tol:
                self.emit(
                    "DI-CHK-01",
                    "field",
                    gross_n,
                    self.cited(gross_n, *(n for n, _ in earnings)),
                    {
                        "formula": "sum of earnings lines",
                        "earnings": {n: str(a) for n, a in earnings},
                        "sum": str(total),
                        "gross": str(gross),
                        "difference": str(abs(total - gross)),
                        "tolerance": str(self.tol),
                    },
                    earnings_sum=display_amount(total),
                    gross=display_amount(gross),
                )

        if gross is None or deductions is None or net is None:  # DI-CHK-02
            lacking = self.missing(self.amount, gross_n, ded_n, net_n)
            self.cannot_check("DI-CHK-02", "that gross pay minus deductions is net pay", lacking)
        else:
            expected = gross - deductions
            if abs(expected - net) > self.tol:
                self.emit(
                    "DI-CHK-02",
                    "field",
                    net_n,
                    self.cited(gross_n, ded_n, net_n),
                    {
                        "formula": "gross - deductions",
                        "gross": str(gross),
                        "deductions": str(deductions),
                        "expected": str(expected),
                        "printed": str(net),
                        "difference": str(abs(expected - net)),
                        "tolerance": str(self.tol),
                    },
                    gross=display_amount(gross),
                    deductions=display_amount(deductions),
                    expected=display_amount(expected),
                    printed=display_amount(net),
                )

        if gross is not None and ytd is not None and ytd < gross:  # DI-CHK-04
            self.emit(
                "DI-CHK-04",
                "field",
                ytd_n,
                self.cited(ytd_n, gross_n),
                {"ytd": str(ytd), "current": str(gross)},
                ytd=display_amount(ytd),
                current=display_amount(gross),
            )

    # bank statement --------------------------------------------------------------------------

    def transactions(self) -> list[dict[str, Any]]:
        indexes = sorted(
            {
                int(m[0])
                for name in self.inp.fields
                if (m := self.cfg.transaction_match(self.inp.doc_type, name))
            }
        )
        rows: list[dict[str, Any]] = []
        for i in indexes:
            names = {
                part: self.cfg.transaction_field(self.inp.doc_type, i, part)
                for part in ("date", "description", "amount", "balance")
            }
            desc = self.field(names["description"])
            rows.append(
                {
                    "names": names,
                    "date": self.date(names["date"]),
                    "description": desc.normalized if desc and desc.present else "",
                    "amount": self.amount(names["amount"]),
                    "balance": self.amount(names["balance"]),
                }
            )
        return rows

    def check_bank_statement(self) -> None:
        open_n, close_n = self.role("opening"), self.role("closing")
        dep_n, wd_n = self.role("total_deposits"), self.role("total_withdrawals")
        start_n, end_n = self.role("period_start"), self.role("period_end")
        opening, closing = self.amount(open_n), self.amount(close_n)
        txns = self.transactions()
        amounts = [t["amount"] for t in txns if t["amount"] is not None]

        if opening is None or closing is None or not amounts:  # DI-CHK-05
            lacking = self.missing(self.amount, open_n, close_n) + (
                [] if amounts else ["transactions"]
            )
            self.cannot_check("DI-CHK-05", "that the balances add up", lacking)
        else:
            net_change = sum(amounts, _ZERO)
            expected = opening + net_change
            if abs(expected - closing) > self.tol:
                self.emit(
                    "DI-CHK-05",
                    "field",
                    close_n,
                    self.cited(open_n, close_n),
                    {
                        "formula": "opening + sum of transactions",
                        "opening": str(opening),
                        "transactions": str(net_change),
                        "expected": str(expected),
                        "closing": str(closing),
                        "difference": str(abs(expected - closing)),
                        "tolerance": str(self.tol),
                        "transaction_count": len(amounts),
                    },
                    opening=display_amount(opening),
                    transactions=display_amount(net_change),
                    expected=display_amount(expected),
                    closing=display_amount(closing),
                )

        deposits = sum((a for a in amounts if a > 0), _ZERO)  # DI-CHK-06
        withdrawals = -sum((a for a in amounts if a < 0), _ZERO)
        for name, listed in ((dep_n, deposits), (wd_n, withdrawals)):
            if not name:
                continue
            printed = self.amount(name)
            if printed is None or not amounts:
                self.cannot_check(
                    "DI-CHK-06", "the printed totals", self.missing(self.amount, name)
                )
            elif abs(printed - listed) > self.tol:
                self.emit(
                    "DI-CHK-06",
                    "field",
                    name,
                    self.cited(name),
                    {"printed": str(printed), "listed": str(listed), "tolerance": str(self.tol)},
                    what=self.label(name).lower(),
                    printed=display_amount(printed),
                    listed=display_amount(listed),
                )

        previous = opening  # DI-CHK-07: report the first balance that does not follow
        for t in txns:
            if t["amount"] is None or t["balance"] is None:
                continue
            if previous is not None and abs(previous + t["amount"] - t["balance"]) > self.tol:
                expected_balance = previous + t["amount"]
                self.emit(
                    "DI-CHK-07",
                    "field",
                    t["names"]["balance"],
                    self.cited(t["names"]["balance"], t["names"]["amount"]),
                    {
                        "previous": str(previous),
                        "amount": str(t["amount"]),
                        "expected": str(expected_balance),
                        "printed": str(t["balance"]),
                    },
                    date=t["date"].isoformat() if t["date"] else "?",
                    description=t["description"],
                    printed=display_amount(t["balance"]),
                    expected=display_amount(expected_balance),
                )
                break
            previous = t["balance"]

        start, end = self.date(start_n), self.date(end_n)  # DI-CHK-08
        if start is None or end is None:
            self.cannot_check(
                "DI-CHK-08",
                "that transactions fall inside the statement period",
                self.missing(self.date, start_n, end_n),
            )
        elif start > end:
            self.emit(
                "DI-CHK-08",
                "field",
                start_n,
                self.cited(start_n, end_n),
                {"start": start.isoformat(), "end": end.isoformat()},
                template="DI-CHK-08:period",
                start=start.isoformat(),
                end=end.isoformat(),
            )
        else:
            for t in txns:
                if t["date"] is not None and not (start <= t["date"] <= end):
                    self.emit(
                        "DI-CHK-08",
                        "field",
                        t["names"]["date"],
                        self.cited(t["names"]["date"]),
                        {
                            "date": t["date"].isoformat(),
                            "start": start.isoformat(),
                            "end": end.isoformat(),
                        },
                        date=t["date"].isoformat(),
                        start=start.isoformat(),
                        end=end.isoformat(),
                    )

    # pages and signs of an incomplete document ------------------------------------------------

    def check_pages(self) -> None:
        labels: list[tuple[int, int]] = []
        for page in self.inp.pages:
            m = PAGE_LABEL.search(page.printed_label or "")
            if m:
                labels.append((int(m.group(1)), int(m.group(2))))
        parts: list[str] = []
        evidence: list[str] = []
        working: dict[str, Any] = {"uploaded": len(self.inp.pages)}
        uploaded = len(self.inp.pages)
        if labels:
            total = max(y for _, y in labels)
            working.update(
                printed_total=total, printed_labels=[f"Page {x} of {y}" for x, y in labels]
            )
            if uploaded != total:
                seen = {x for x, _ in labels}
                gone = [n for n in range(1, total + 1) if n not in seen]
                if uploaded < total and gone:
                    missing = (
                        f"page {gone[0]} is missing"
                        if len(gone) == 1
                        else "pages " + ", ".join(map(str, gone)) + " are missing"
                    )
                else:
                    missing = "the number of pages does not match"
                _, text = self.rules.flag(
                    "DI-W701", total=total, uploaded=uploaded, missing=missing
                )
                parts.append(text)
                evidence += [r for r, ln in self.inp.lines.items() if PAGE_LABEL.search(ln.text)]
        for signal in self.inp.signals:
            _, text = self.rules.flag("DI-W701:signal", signal=signal)
            parts.append(text)
        if parts:
            self.findings.append(
                Finding(
                    "DI-W701",
                    self.rules.severity("DI-W701"),
                    " ".join(parts),
                    "document",
                    None,
                    tuple(evidence),
                    working,
                )
            )

    # certainty -------------------------------------------------------------------------------

    def certainty(self) -> dict[str, str]:
        """FSD 4.4. Low: the value or its source was not found, the reader said low, or a cited
        line is below the OCR threshold. High: found, the reader said high, lines meet it.
        Medium: everything else."""
        out: dict[str, str] = {}
        for name, f in self.inp.fields.items():
            if f.present and f.review_status in REVIEWED and f.normalized is not None:
                out[name] = "high"  # checked by a person
                continue
            if not f.present or not self.found.get(name, False) or f.certainty == "low":
                out[name] = "low"
                continue
            cited = [self.inp.lines[r] for r in f.lines if r in self.inp.lines]
            under = any(c.confidence is not None and c.confidence < self.min_conf for c in cited)
            out[name] = "low" if under else ("high" if f.certainty == "high" else "medium")
        return out


def validate(
    inp: ValidationInput, rules: ValidationConfig, cfg: DocumentFieldsConfig
) -> ValidationReport:
    """Run every check that applies to this document's type."""
    run = _Checks(inp, rules, cfg)
    run.check_fields()
    if not cfg.has_fields(inp.doc_type) and not inp.fields:
        # A type no reader is configured for yet (for example a W-2): say so instead of passing.
        run.emit("DI-W604", "document", None, (), template="DI-W604:none")
    if inp.doc_type == "pay_stub":
        run.check_pay_stub()
    elif inp.doc_type == "bank_statement":
        run.check_bank_statement()
    run.check_pages()
    run.flush_cannot_checks()
    return ValidationReport(tuple(run.findings), run.certainty(), run.found)

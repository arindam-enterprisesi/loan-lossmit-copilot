"""A rule-based reader that stands in for the model (classify, extract) until the real tasks exist.

It reads only the numbered lines it is given, and reads what is PRINTED: Daniel's pay stub gives net
pay ``2,083.61`` on ``p1-L31``, which is what lets the arithmetic check catch it. It understands the
synthetic documents this project generates (``data/synthetic``): a pay stub and a bank statement in
full, and the title lines of every other type. Anything else comes back unrecognised or empty, never
guessed. Every result is stamped provider ``fake`` so it can never be mistaken for a model's.
"""

from __future__ import annotations

import re
from collections.abc import Sequence

from app.services.classification import Classification
from app.services.doc_lines import DocLine
from app.services.extractor import ExtractedField, ExtractionOutcome

PROVIDER = "fake"
MODEL = "rule-based-v1"

# (type, title pattern, certainty). The first pattern that matches in the first two pages wins.
CLASSIFY_RULES: tuple[tuple[str, re.Pattern[str], str], ...] = (
    ("pay_stub", re.compile(r"\bEARNINGS STATEMENT\b"), "high"),
    ("bank_statement", re.compile(r"\bSTATEMENT OF ACCOUNT\b"), "high"),
    ("w2", re.compile(r"\bForm W-2\b"), "high"),
    ("tax_return_1040", re.compile(r"\bForm 1040\b"), "high"),
    ("credit_report", re.compile(r"\bCREDIT REPORT\b", re.IGNORECASE), "high"),
    ("mortgage_assistance_application", re.compile(r"\bMORTGAGE ASSISTANCE APPLICATION\b"), "high"),
    ("mortgage_statement", re.compile(r"\bMORTGAGE STATEMENT\b"), "high"),
    ("expense_bill", re.compile(r"\b(UTILITY BILL|INVOICE)\b"), "high"),
    ("hardship_letter", re.compile(r"\bDear Loss Mitigation\b"), "high"),
    ("benefits_letter", re.compile(r"\bbenefit (payments?|letter)\b", re.IGNORECASE), "medium"),
    ("hardship_letter", re.compile(r"\bhardship\b", re.IGNORECASE), "medium"),
)
CLASSIFY_PAGES = 2  # the real classify task also reads only the first two pages


class FakeClassifier:
    async def classify(self, lines: Sequence[DocLine]) -> Classification:
        first = [ln for ln in lines if ln.page <= CLASSIFY_PAGES]
        for doc_type, pattern, certainty in CLASSIFY_RULES:
            cited = [ln.ref for ln in first if pattern.search(ln.text)][:5]
            if cited:
                return Classification(doc_type, certainty, cited, [], PROVIDER, MODEL)
        return Classification("unrecognized", "low", [], [], PROVIDER, MODEL)


# --- extraction -----------------------------------------------------------------------------

_AMOUNT = r"-?\(?\$?[\d,]+\.\d{2}\)?"
_AMOUNTS = re.compile(_AMOUNT)
_PERIOD = re.compile(r"^Pay period:\s*(\S+)\s+to\s+(\S+)\s*$")
_STATEMENT_PERIOD = re.compile(r"^Statement period:\s*(\S+)\s+to\s+(\S+)\s*$")
_TXN = re.compile(rf"^(\d{{4}}-\d{{2}}-\d{{2}})\s+(.+?)\s+({_AMOUNT})\s+({_AMOUNT})\s*$")


class _Reader:
    def __init__(self, lines: Sequence[DocLine]) -> None:
        self.lines = list(lines)
        self.fields: dict[str, ExtractedField] = {}

    def put(self, name: str, value: str | None, ref: str, certainty: str = "high") -> None:
        if value is not None and name not in self.fields:
            self.fields[name] = ExtractedField(value, [ref], certainty)

    def match(self, pattern: str | re.Pattern[str]) -> tuple[DocLine, re.Match[str]] | None:
        compiled = re.compile(pattern) if isinstance(pattern, str) else pattern
        for ln in self.lines:
            found = compiled.search(ln.text)
            if found:
                return ln, found
        return None

    def take(self, name: str, pattern: str | re.Pattern[str], group: int = 1) -> None:
        hit = self.match(pattern)
        if hit:
            self.put(name, hit[1].group(group).strip(), hit[0].ref)


def _read_pay_stub(lines: Sequence[DocLine]) -> ExtractionOutcome:
    r = _Reader(lines)
    first = next((ln for ln in r.lines if ln.page == 1), None)
    if first and any(ln.page == 1 and "EARNINGS STATEMENT" in ln.text for ln in r.lines[:8]):
        r.put("employer_name", first.text.strip(), first.ref)
    r.take("employee_name", r"^Employee:\s*(.+)$")
    period = r.match(_PERIOD)
    if period:
        r.put("pay_period_start", period[1].group(1), period[0].ref)
        r.put("pay_period_end", period[1].group(2), period[0].ref)
    r.take("pay_date", r"^Pay date:\s*(\S+)\s*$")
    r.take("account_last4", r"[Aa]ccount ending\s+(\d{4})\b")

    in_earnings = False  # the EARNINGS block: one row per earnings kind, until "Gross Pay"
    for ln in r.lines:
        if ln.text.startswith("EARNINGS"):
            in_earnings = True
        elif ln.text.startswith("Gross Pay"):
            in_earnings = False
        elif in_earnings:
            word = ln.text.split(" ", 1)[0].lower()
            amounts = _AMOUNTS.findall(ln.text)
            if word.isalpha() and len(amounts) >= 2:
                r.put(f"earnings_{word}_current", amounts[-2], ln.ref)

    gross = r.match(r"^Gross Pay\s")
    if gross:
        amounts = _AMOUNTS.findall(gross[0].text)
        if len(amounts) >= 2:
            r.put("gross_pay_current", amounts[-2], gross[0].ref)
    deductions = r.match(r"^Total Deductions\s")
    if deductions:
        amounts = _AMOUNTS.findall(deductions[0].text)
        if len(amounts) >= 2:
            r.put("total_deductions_current", amounts[-2], deductions[0].ref)
    r.take("net_pay_current", rf"^Net Pay\s+({_AMOUNT})\s*$")
    r.take("gross_pay_ytd", rf"^Gross pay, year to date\s+({_AMOUNT})\s*$")
    r.take("net_pay_ytd", rf"^Net pay, year to date\s+({_AMOUNT})\s*$")
    return ExtractionOutcome(r.fields, [], PROVIDER, MODEL, "fake-extract@1")


def _read_bank_statement(lines: Sequence[DocLine]) -> ExtractionOutcome:
    r = _Reader(lines)
    first = next((ln for ln in r.lines if ln.page == 1), None)
    if first:
        r.put("institution_name", first.text.strip(), first.ref)
    r.take("account_holder", r"^Account holder:\s*(.+)$")
    r.take("account_last4", r"\bending\s+(\d{4})\b")
    period = r.match(_STATEMENT_PERIOD)
    if period:
        r.put("statement_period_start", period[1].group(1), period[0].ref)
        r.put("statement_period_end", period[1].group(2), period[0].ref)
    r.take("opening_balance", rf"^Opening balance\s+({_AMOUNT})\s*$")
    r.take("closing_balance", rf"^Closing balance\s+({_AMOUNT})\s*$")
    r.take("total_deposits", rf"^Total deposits and credits\s+({_AMOUNT})\s*$")
    r.take("total_withdrawals", rf"^Total withdrawals and debits\s+({_AMOUNT})\s*$")
    number = 0
    for ln in r.lines:
        row = _TXN.match(ln.text)
        if row:
            number += 1
            date, description, amount, balance = row.groups()
            for part, value in (
                ("date", date),
                ("description", description),
                ("amount", amount),
                ("balance", balance),
            ):
                r.put(f"txn_{number:03d}_{part}", value, ln.ref)
    return ExtractionOutcome(r.fields, [], PROVIDER, MODEL, "fake-extract@1")


class FakeExtractor:
    async def extract(self, doc_type: str, lines: Sequence[DocLine]) -> ExtractionOutcome:
        if doc_type == "pay_stub":
            return _read_pay_stub(lines)
        if doc_type == "bank_statement":
            return _read_bank_statement(lines)
        return ExtractionOutcome({}, [], PROVIDER, MODEL, "fake-extract@1")

"""A rule-based reader that stands in for the model (classify, extract) until the real tasks exist.

It reads only the numbered lines it is given, and reads what is PRINTED: Daniel's pay stub gives net
pay ``2,083.61`` on ``p1-L31``, which is what lets the arithmetic check catch it. It understands the
synthetic documents this project generates (``data/synthetic``): a pay stub, a bank statement, a
credit report, a mortgage statement and a mortgage assistance application in full, and the title
lines of every other type. Anything else comes back unrecognised or empty, never guessed. Every
result is stamped provider ``fake`` so it can never be mistaken for a model's.
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
    r.take("pay_frequency", r"^Pay frequency:\s*(.+?)\s*$")
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


_DATE = r"\d{4}-\d{2}-\d{2}"
_NOTHING = {"none", "n/a", ""}  # what a report prints for "no value"
_TRADELINE = re.compile(
    rf"^(?P<creditor>.+?) \| (?P<kind>\w+) \| (?P<owner>\w+) \| opened (?P<opened>{_DATE}) "
    r"\| status (?P<status>.+)$"
)
_TRADELINE_AMOUNTS = re.compile(
    rf"^Balance ({_AMOUNT}) Limit ({_AMOUNT}|n/a) Monthly payment ({_AMOUNT}) Past due ({_AMOUNT})$"
)
_TRADELINE_LATE = re.compile(
    rf"^Late payments: 30-day (\d+), 60-day (\d+), 90-day (\d+) Most recent late: ({_DATE}|none)$"
)


def _read_credit_report(lines: Sequence[DocLine]) -> ExtractionOutcome:
    """Scores, tradelines, inquiries and alerts of the generated sample credit report."""
    r = _Reader(lines)
    r.take("report_date", rf"^Report date:\s*({_DATE})\s*$")
    consumer = r.match(r"^Consumer:\s*(.+?)(?:\s+SSN\b.*)?$")
    if consumer:
        r.put("consumer_name", consumer[1].group(1).strip(), consumer[0].ref)
    r.take("alerts", r"^Alerts:\s*(.+)$")
    scores = tradelines = inquiries = 0
    section = ""
    current: int | None = None
    for ln in r.lines:
        text = ln.text.strip()
        if text in {"SCORES", "TRADELINES", "INQUIRIES"}:
            section = text
            continue
        if text.startswith(("Collections:", "Public records:")):
            section = ""
        if section == "SCORES":
            found = re.match(r"^(Bureau \w+) score (\d{3})$", text)
            if found:
                scores += 1
                r.put(f"score_{scores:03d}_bureau", found.group(1), ln.ref)
                r.put(f"score_{scores:03d}_value", found.group(2), ln.ref)
        elif section == "TRADELINES":
            head = _TRADELINE.match(text)
            amounts = _TRADELINE_AMOUNTS.match(text)
            late = _TRADELINE_LATE.match(text)
            if head:
                tradelines += 1
                current = tradelines
                for part, value in (
                    ("creditor", head["creditor"]),
                    ("account_type", head["kind"]),
                    ("ownership", head["owner"]),
                    ("open_date", head["opened"]),
                    ("status", head["status"]),
                ):
                    r.put(f"tradeline_{current:03d}_{part}", value, ln.ref)
            elif amounts and current:
                for part, value in zip(
                    ("balance", "credit_limit", "monthly_payment", "past_due"),
                    amounts.groups(),
                    strict=True,
                ):
                    if value.lower() not in _NOTHING:
                        r.put(f"tradeline_{current:03d}_{part}", value, ln.ref)
            elif late and current:
                for part, value in zip(
                    ("late_30", "late_60", "late_90", "most_recent_late"),
                    late.groups(),
                    strict=True,
                ):
                    if value.lower() not in _NOTHING:
                        r.put(f"tradeline_{current:03d}_{part}", value, ln.ref)
            elif text.startswith("Remarks:") and current:
                remark = text.split(":", 1)[1].strip()
                if remark.lower() not in _NOTHING:
                    r.put(f"tradeline_{current:03d}_remarks", remark, ln.ref)
        elif section == "INQUIRIES":
            found = re.match(rf"^(.+?)\s+({_DATE})$", text)
            if found:
                inquiries += 1
                r.put(f"inquiry_{inquiries:03d}_creditor", found.group(1), ln.ref)
                r.put(f"inquiry_{inquiries:03d}_date", found.group(2), ln.ref)
    return ExtractionOutcome(r.fields, [], PROVIDER, MODEL, "fake-extract@1")


def _read_mortgage_statement(lines: Sequence[DocLine]) -> ExtractionOutcome:
    """The parts of the generated mortgage statement the loan record and the budget read."""
    r = _Reader(lines)
    first = next((ln for ln in r.lines if ln.page == 1), None)
    if first:
        r.put("servicer", first.text.strip(), first.ref)
    r.take("statement_date", rf"^Statement date:\s*({_DATE})\s*$")
    r.take("loan_number", r"^Loan number:\s*(\S+)\s*$")
    r.take("borrower_names", r"^Borrower:\s*(.+)$")
    r.take("unpaid_principal_balance", rf"^Unpaid principal balance\s+({_AMOUNT})\s*$")
    r.take("interest_rate", r"^Interest rate\s+(\S+)\s*$")
    r.take("payment_due_date", rf"^Payment due date:\s*({_DATE})\s*$")
    r.take("principal_and_interest", rf"^Principal and interest\s+({_AMOUNT})\s*$")
    r.take("escrow", rf"^Escrow[^\d]*\s({_AMOUNT})\s*$")
    r.take("regular_monthly_payment", rf"^Monthly payment\s+({_AMOUNT})\s*$")
    r.take("past_due_amount", rf"^Past due amount\s+({_AMOUNT})\s*$")
    r.take("fees", rf"^Late fees\s+({_AMOUNT})\s*$")
    r.take("total_amount_due", rf"^Total amount due\s+({_AMOUNT})\s*$")
    return ExtractionOutcome(r.fields, [], PROVIDER, MODEL, "fake-extract@1")


_ROW = re.compile(rf"^(.+?)\s+({_AMOUNT})\s*$")
_APPLICATION_SECTIONS = {
    "REASON FOR HARDSHIP": "reasons",
    "MONTHLY INCOME": "income",
    "MONTHLY EXPENSES": "expenses",
    "ASSETS": "assets",
}
_APPLICATION_PREFIX = {
    "income": "monthly_income_",
    "expenses": "monthly_expenses_",
    "assets": "assets_",
}


def _read_application(lines: Sequence[DocLine]) -> ExtractionOutcome:
    """The generated mortgage assistance application: the reasons ticked, the intent, and the
    stated income, expenses and assets as the borrower wrote them."""
    r = _Reader(lines)
    r.take("borrower_names", r"^Borrower:\s*(.+)$")
    r.take("loan_number", r"^Loan number:\s*(\S+)\s*$")
    r.take("property_address", r"^Property address:\s*(.+)$")
    r.take("occupancy", r"^Occupancy:\s*(.+)$")
    r.take("intent", r"^What do you want to do with the home\?\s*(.+)$")
    r.take("signed_date", rf"Date signed:\s*({_DATE})\s*$")
    section = ""
    counts = {"reasons": 0, "income": 0, "expenses": 0, "assets": 0}
    for ln in r.lines:
        text = ln.text.strip()
        if text in _APPLICATION_SECTIONS:
            section = _APPLICATION_SECTIONS[text]
            continue
        if text.startswith(("What do you want", "Documents enclosed")):
            section = ""
        if section == "reasons":
            ticked = re.match(r"^\[[xX]\]\s*(.+)$", text)
            if ticked:
                counts["reasons"] += 1
                r.put(f"hardship_reasons_{counts['reasons']:03d}_reason", ticked.group(1), ln.ref)
            continue
        row = _ROW.match(text)
        if not row or not section:
            continue
        description, amount = row.groups()
        if section == "expenses" and description.lower().startswith("total monthly expenses"):
            r.put("total_monthly_expenses", amount, ln.ref)
            continue
        counts[section] += 1
        prefix = f"{_APPLICATION_PREFIX[section]}{counts[section]:03d}"
        r.put(f"{prefix}_description", description, ln.ref)
        r.put(f"{prefix}_amount", amount, ln.ref)
    return ExtractionOutcome(r.fields, [], PROVIDER, MODEL, "fake-extract@1")


class FakeExtractor:
    async def extract(self, doc_type: str, lines: Sequence[DocLine]) -> ExtractionOutcome:
        if doc_type == "pay_stub":
            return _read_pay_stub(lines)
        if doc_type == "bank_statement":
            return _read_bank_statement(lines)
        if doc_type == "credit_report":
            return _read_credit_report(lines)
        if doc_type == "mortgage_statement":
            return _read_mortgage_statement(lines)
        if doc_type == "mortgage_assistance_application":
            return _read_application(lines)
        return ExtractionOutcome({}, [], PROVIDER, MODEL, "fake-extract@1")

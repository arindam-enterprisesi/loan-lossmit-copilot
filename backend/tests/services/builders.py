"""Builders for validation tests: a pay stub and a bank statement as the checks receive them."""

from __future__ import annotations

from collections.abc import Mapping

from app.services.document_config import get_document_fields
from app.services.normalize import normalize
from app.services.validation import FieldInput, LineInput, PageInput, ValidationInput

CFG = get_document_fields()

Values = Mapping[str, tuple[str | None, tuple[str, ...]]]


def make_field(
    doc_type: str,
    name: str,
    value: str | None,
    lines: tuple[str, ...] = (),
    *,
    certainty: str = "high",
    review: str = "unreviewed",
) -> FieldInput:
    kind = CFG.kind_of(doc_type, name)
    spec = CFG.field_spec(doc_type, name)
    return FieldInput(
        name=name,
        value=value,
        normalized=normalize(kind, value) if value is not None else None,
        kind=kind,
        lines=lines,
        certainty=certainty,
        review_status=review,
        required=bool(spec and spec.required),
    )


# Daniel Reyes's pay stub, line by line as printed (Feature Design 1.8 and 3.8).
STUB_LINES = {
    "p1-L1": "Cedar Valley Manufacturing, Inc.",
    "p1-L5": "Employee: Daniel Reyes",
    "p1-L9": "Pay period: 2026-09-14 to 2026-09-27",
    "p1-L10": "Pay date: 2026-10-02",
    "p1-L12": "Direct deposit: account ending 6032",
    "p1-L14": "Regular 80.00 34.50 2,760.00 52,440.00",
    "p1-L15": "Overtime 1.5x 3.96 51.75 204.93 3,897.10",
    "p1-L16": "Bonus 105.57 2,002.40",
    "p1-L17": "Gross Pay 3,070.50 58,339.50",
    "p1-L25": "Total Deductions 1,036.89 19,700.91",
    "p1-L29": "Gross pay, year to date 58,339.50",
    "p1-L31": "Net Pay 2,083.61",
    "p1-L32": "Net pay, year to date 38,638.59",
    "p1-L34": "Page 1 of 2",
    "p2-L19": "Page 2 of 2",
}

STUB_VALUES: dict[str, tuple[str | None, tuple[str, ...]]] = {
    "employer_name": ("Cedar Valley Manufacturing, Inc.", ("p1-L1",)),
    "employee_name": ("Daniel Reyes", ("p1-L5",)),
    "pay_period_start": ("2026-09-14", ("p1-L9",)),
    "pay_period_end": ("2026-09-27", ("p1-L9",)),
    "pay_date": ("2026-10-02", ("p1-L10",)),
    "earnings_regular_current": ("2,760.00", ("p1-L14",)),
    "earnings_overtime_current": ("204.93", ("p1-L15",)),
    "earnings_bonus_current": ("105.57", ("p1-L16",)),
    "gross_pay_current": ("3,070.50", ("p1-L17",)),
    "total_deductions_current": ("1,036.89", ("p1-L25",)),
    "net_pay_current": ("2,083.61", ("p1-L31",)),  # as printed: the true net pay is 2,033.61
    "gross_pay_ytd": ("58,339.50", ("p1-L29",)),
    "net_pay_ytd": ("38,638.59", ("p1-L32",)),
    "account_last4": ("ending 6032", ("p1-L12",)),
}


def pay_stub(
    overrides: Values | None = None,
    *,
    lines: Mapping[str, str] | None = None,
    pages: tuple[PageInput, ...] = (PageInput(1, "Page 1 of 2"), PageInput(2, "Page 2 of 2")),
    signals: tuple[str, ...] = (),
    drop: tuple[str, ...] = (),
) -> ValidationInput:
    values = {**STUB_VALUES, **(overrides or {})}
    fields = {
        name: make_field("pay_stub", name, value, refs)
        for name, (value, refs) in values.items()
        if name not in drop
    }
    texts = dict(lines if lines is not None else STUB_LINES)
    return ValidationInput(
        "pay_stub", fields, {r: LineInput(r, t) for r, t in texts.items()}, pages, signals
    )


# A small, correct bank statement: opening 1,000.00, two transactions, closing 950.00.
BANK_LINES = {
    "p1-L1": "Fairhaven Community Bank",
    "p1-L4": "Account holder: Daniel Reyes",
    "p1-L5": "Everyday Checking ending 6032",
    "p1-L6": "Statement period: 2026-08-01 to 2026-08-31",
    "p1-L8": "Opening balance 1,000.00",
    "p1-L9": "Total deposits and credits 50.00",
    "p1-L10": "Total withdrawals and debits 100.00",
    "p1-L11": "Closing balance 950.00",
    "p1-L14": "2026-08-01 OAKMONT APARTMENTS RENT -100.00 900.00",
    "p1-L15": "2026-08-05 PAYROLL 50.00 950.00",
    "p1-L16": "Page 1 of 1",
}


def txn(
    i: int, date: str, desc: str, amount: str, balance: str, ref: str
) -> dict[str, tuple[str | None, tuple[str, ...]]]:
    return {
        f"txn_{i:03d}_date": (date, (ref,)),
        f"txn_{i:03d}_description": (desc, (ref,)),
        f"txn_{i:03d}_amount": (amount, (ref,)),
        f"txn_{i:03d}_balance": (balance, (ref,)),
    }


BANK_VALUES: dict[str, tuple[str | None, tuple[str, ...]]] = {
    "institution_name": ("Fairhaven Community Bank", ("p1-L1",)),
    "account_holder": ("Daniel Reyes", ("p1-L4",)),
    "account_last4": ("ending 6032", ("p1-L5",)),
    "statement_period_start": ("2026-08-01", ("p1-L6",)),
    "statement_period_end": ("2026-08-31", ("p1-L6",)),
    "opening_balance": ("1,000.00", ("p1-L8",)),
    "closing_balance": ("950.00", ("p1-L11",)),
    "total_deposits": ("50.00", ("p1-L9",)),
    "total_withdrawals": ("100.00", ("p1-L10",)),
    **txn(1, "2026-08-01", "OAKMONT APARTMENTS RENT", "-100.00", "900.00", "p1-L14"),
    **txn(2, "2026-08-05", "PAYROLL", "50.00", "950.00", "p1-L15"),
}


def bank_statement(
    overrides: Values | None = None,
    *,
    pages: tuple[PageInput, ...] = (PageInput(1, "Page 1 of 1"),),
    drop: tuple[str, ...] = (),
) -> ValidationInput:
    values = {**BANK_VALUES, **(overrides or {})}
    fields = {
        name: make_field("bank_statement", name, value, refs)
        for name, (value, refs) in values.items()
        if name not in drop
    }
    return ValidationInput(
        "bank_statement", fields, {r: LineInput(r, t) for r, t in BANK_LINES.items()}, pages
    )

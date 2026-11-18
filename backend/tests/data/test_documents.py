# ruff: noqa: I001
"""Re-read every rendered PDF and confirm its figures match the scenario file."""

from __future__ import annotations

import re
from datetime import date
from decimal import Decimal

import pytest

from tests.data.conftest import Rendered
from tests.data.helpers import D, flat, fmt, read_pages
from synthetic.schema import (
    BankStatementDoc,
    Document,
    HardshipLetterDoc,
    PayStubDoc,
    load_scenario,
    running_balances,
    scenario_names,
    statement_pages,
)

ALL_DOCS = [(name, doc) for name in scenario_names() for doc in load_scenario(name).documents]
IDS = [f"{name}/{doc.id}" for name, doc in ALL_DOCS]

AMOUNT = re.compile(r"-?\d[\d,]*\.\d{2}")
TXN_ROW = re.compile(r"^(\d{4}-\d{2}-\d{2}) (.+?) (-?[\d,]+\.\d{2}) (-?[\d,]+\.\d{2})$")


def pdf_path(rendered: Rendered, name: str, doc: Document):
    folder = "withheld/" if doc.role == "withheld" else ""
    return rendered.path(f"{name}/{folder}{doc.file_name}")


def amounts(line: str) -> list[Decimal]:
    return [D(a.replace(",", "")) for a in AMOUNT.findall(line)]


def line_starting(lines: list[str], prefix: str) -> str:
    return next(line for line in lines if line.startswith(prefix))


def iso(value: date) -> str:
    return value.isoformat()


def required_text(doc: Document) -> list[str]:
    f = doc.facts
    match doc.type:
        case "pay_stub":
            t = [f.employer.name, f.employer.address, f.employer.ein, f.employee, f.employee_id]
            t += [f.address, f.pay_frequency, f"{iso(f.period_start)} to {iso(f.period_end)}"]
            t += [iso(f.pay_date), f"Pay period {f.period_number} of {f.periods_per_year}"]
            t += [f"ending {f.direct_deposit_last4}", f"Page 1 of {f.pages}"]
            for e in f.earnings:
                t += [e.description, fmt(e.current), fmt(e.ytd)]
                t += [fmt(e.hours)] if e.hours is not None else []
                t += [fmt(e.rate)] if e.rate is not None else []
            for d in f.deductions:
                t += [d.description, fmt(d.current), fmt(d.ytd)]
            printed = f.printed_net_current if f.printed_net_current is not None else f.net_current
            t += [fmt(x) for x in (f.gross_current, f.gross_ytd, f.deductions_current)]
            t += [fmt(f.deductions_ytd), fmt(printed), fmt(f.net_ytd)]
            return t
        case "bank_statement":
            t = [f.bank, f.bank_address, f.account_holder, f"ending {f.account_last4}"]
            t += [f"{iso(f.period_start)} to {iso(f.period_end)}", fmt(f.opening_balance)]
            t += [fmt(f.closing_balance)] if f.pages_rendered == f.total_pages_printed else []
            for page in statement_pages(f)[: f.pages_rendered]:
                for txn in page:
                    t += [iso(txn.date), txn.description, fmt(txn.amount)]
            return t
        case "w2":
            t = [str(f.tax_year), f.employer.name, f.employer.ein, f.employer.address, f.employee]
            t += [f"XXX-XX-{f.ssn_last4}", f.address]
            t += [fmt(x) for x in (f.box1, f.box2, f.box3, f.box4, f.box5, f.box6)]
            for b in f.box12:
                t += [f"Code {b.code}", fmt(b.amount)]
            return t
        case "tax_return_1040":
            t = [str(f.tax_year), f.filing_status, f.taxpayer, f"XXX-XX-{f.ssn_last4}", f.address]
            return (
                t
                + [fmt(x) for x in (f.wages, f.taxable_interest, f.total_income, f.adjustments)]
                + [fmt(f.adjusted_gross_income)]
            )
        case "credit_report":
            t = [iso(f.report_date), f.consumer, f"XXX-XX-{f.ssn_last4}", f.address]
            for s in f.scores:
                t += [s.bureau, str(s.score)]
            for tl in f.tradelines:
                t += [tl.creditor, tl.account_type, iso(tl.open_date), tl.status, fmt(tl.balance)]
                t += [fmt(tl.monthly_payment), fmt(tl.past_due)]
                t += [fmt(tl.credit_limit)] if tl.credit_limit is not None else []
                t += [iso(tl.most_recent_late)] if tl.most_recent_late else []
            for q in f.inquiries:
                t += [q.creditor, iso(q.date)]
            return t
        case "mortgage_statement":
            t = [f.servicer, iso(f.statement_date), f.loan_number, f.borrower, f.property_address]
            t += [f"{f.interest_rate_pct}%", iso(f.payment_due_date), f.delinquency_notice]
            t += [
                fmt(x)
                for x in (
                    f.unpaid_principal_balance,
                    f.principal_and_interest,
                    f.escrow,
                    f.monthly_payment,
                    f.past_due_amount,
                    f.late_fees,
                    f.total_due,
                )
            ]
            return t + [iso(d) for d in f.payments_past_due]
        case "mortgage_assistance_application":
            t = [f.title.upper(), f.borrower, f.address, f.phone, f.loan_number, f.servicer]
            t += [f.property_address, f.occupancy, f.intent, f.signature, iso(f.signed_date)]
            t += [f"[{'X' if r.checked else ' '}] {r.reason}" for r in f.hardship_reasons]
            t += [fmt(f.monthly_gross_income), fmt(f.other_income), fmt(f.total_expenses)]
            for e in f.expenses:
                t += [e.category, fmt(e.amount)]
            for a in f.assets:
                t += [a.description, fmt(a.amount)]
            return t + list(f.enclosed)
        case "hardship_letter":
            return list(f.lines)
        case "expense_bill":
            t = [f.provider, f.provider_address, f.customer, f.service_address]
            t += [f"ending {f.account_number_last4}", fmt(f.amount_due)]
            return t + [
                iso(d) for d in (f.period_start, f.period_end, f.statement_date, f.due_date)
            ]
    raise AssertionError(doc.type)  # pragma: no cover


@pytest.mark.parametrize(("name", "doc"), ALL_DOCS, ids=IDS)
def test_every_scenario_figure_is_in_the_pdf(rendered: Rendered, name: str, doc: Document) -> None:
    pages = read_pages(pdf_path(rendered, name, doc))
    text = flat(pages)
    missing = [token for token in required_text(doc) if token not in text]
    assert not missing, f"{name}/{doc.id} is missing {missing}"


@pytest.mark.parametrize(("name", "doc"), ALL_DOCS, ids=IDS)
def test_page_count_and_text_layer(rendered: Rendered, name: str, doc: Document) -> None:
    pages = read_pages(pdf_path(rendered, name, doc))
    expected = {
        "pay_stub": lambda d: d.facts.pages,
        "bank_statement": lambda d: d.facts.pages_rendered,
    }.get(doc.type, lambda d: 1)(doc)
    assert len(pages) == expected
    assert (
        rendered.entry(pdf_path(rendered, name, doc).relative_to(rendered.out).as_posix())[
            "page_count"
        ]
        == expected
    )
    for index, lines in enumerate(pages, start=1):
        assert any(line.startswith(f"Page {index} of ") for line in lines)
        assert lines[-1].startswith("SYNTHETIC SAMPLE")


BANK_DOCS = [(n, d) for n, d in ALL_DOCS if isinstance(d, BankStatementDoc)]


@pytest.mark.parametrize(("name", "doc"), BANK_DOCS, ids=[f"{n}/{d.id}" for n, d in BANK_DOCS])
def test_bank_statement_rows_read_back_exactly(
    rendered: Rendered, name: str, doc: BankStatementDoc
) -> None:
    pages = read_pages(pdf_path(rendered, name, doc))
    rows = [m.groups() for page in pages for line in page if (m := TXN_ROW.match(line))]
    f = doc.facts
    shown = [t for page in statement_pages(f)[: f.pages_rendered] for t in page]
    balances = running_balances(f)[: len(shown)]
    assert [(d, desc, D(a.replace(",", "")), D(b.replace(",", ""))) for d, desc, a, b in rows] == [
        (iso(t.date), t.description, t.amount, balance)
        for t, balance in zip(shown, balances, strict=True)
    ]
    summary = line_starting(pages[0], "Opening balance")
    assert amounts(summary) == [f.opening_balance]
    credits = sum((t.amount for t in f.transactions if t.amount > 0), D("0"))
    debits = -sum((t.amount for t in f.transactions if t.amount < 0), D("0"))
    assert amounts(line_starting(pages[0], "Total deposits and credits")) == [credits]
    assert amounts(line_starting(pages[0], "Total withdrawals and debits")) == [debits]
    assert amounts(line_starting(pages[0], "Closing balance")) == [f.closing_balance]


def test_pay_stub_rows_read_back_exactly(rendered: Rendered) -> None:
    for name, doc in ALL_DOCS:
        if not isinstance(doc, PayStubDoc):
            continue
        f = doc.facts
        lines = read_pages(pdf_path(rendered, name, doc))[0]
        assert amounts(line_starting(lines, "Gross Pay")) == [f.gross_current, f.gross_ytd]
        assert amounts(line_starting(lines, "Total Deductions")) == [
            f.deductions_current,
            f.deductions_ytd,
        ]
        for e in f.earnings:
            row = amounts(line_starting(lines, e.description))
            assert row[-2:] == [e.current, e.ytd]
        for d in f.deductions:
            assert amounts(line_starting(lines, d.description)) == [d.current, d.ytd]
        printed = f.printed_net_current if f.printed_net_current is not None else f.net_current
        assert amounts(line_starting(lines, "Net Pay")) == [printed]
        assert amounts(line_starting(lines, "Net pay, year to date")) == [f.net_ytd]


def test_credit_report_tradeline_rows(rendered: Rendered, daniel) -> None:
    doc = daniel.document("credit_report_2026-10-12")
    lines = read_pages(pdf_path(rendered, "daniel_reyes", doc))[0]
    for t in doc.facts.tradelines:
        header = lines.index(next(line for line in lines if line.startswith(t.creditor + " |")))
        values = amounts(lines[header + 1])
        limit = [t.credit_limit] if t.credit_limit is not None else []
        assert values == [t.balance, *limit, t.monthly_payment, t.past_due]
    assert [line for line in lines if line.endswith(("705", "712", "698"))] == [
        "Bureau A score 712",
        "Bureau B score 698",
        "Bureau C score 705",
    ]


def test_same_figures_appear_identically_across_documents(rendered: Rendered) -> None:
    def text(name: str, doc_id: str) -> str:
        doc = load_scenario(name).document(doc_id)
        return flat(read_pages(pdf_path(rendered, name, doc)))

    # Daniel's true net pay is on both September and August statements as payroll deposits
    for statement in ("bank_statement_2026-08", "bank_statement_2026-09"):
        assert text("daniel_reyes", statement).count("CEDAR VALLEY MFG PAYROLL 2,033.61") == 2
    # Angela's 1,720.00 payment: statement, application, and the July bank statement
    for name, doc_id in (
        ("angela_whitfield", "mortgage_statement_2026-10"),
        ("angela_whitfield", "mortgage_assistance_application"),
        ("angela_whitfield", "bank_statement_2026-07"),
    ):
        assert "1,720.00" in text(name, doc_id)
    # 5,160.00 is the arrears on the statement and in her letter
    for doc_id in ("mortgage_statement_2026-10", "hardship_letter"):
        assert "5,160.00" in text("angela_whitfield", doc_id)


@pytest.mark.parametrize("doc", [d for _, d in ALL_DOCS if isinstance(d, HardshipLetterDoc)])
def test_hardship_letter_lines_are_exact(rendered: Rendered, doc: HardshipLetterDoc) -> None:
    lines = read_pages(pdf_path(rendered, "angela_whitfield", doc))[0]
    assert lines[: len(doc.facts.lines)] == doc.facts.lines

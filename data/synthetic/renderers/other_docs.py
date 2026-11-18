"""Loss mitigation documents (application, letter, mortgage statement) and a utility bill."""

from __future__ import annotations

from synthetic.layout import LEFT, RIGHT, Page, Seg
from synthetic.schema import (
    ApplicationDoc,
    HardshipLetterDoc,
    MortgageStatementDoc,
    UtilityBillDoc,
)
from synthetic.schema import (
    money_text as m,
)


def _pair(page: Page, label: str, value: str, *, bold: bool = False) -> None:
    page.cols(Seg(LEFT, label), Seg(RIGHT, value, "r"), bold=bold)


def render_mortgage_statement(doc: MortgageStatementDoc) -> list[Page]:
    f = doc.facts
    p = Page()
    p.line(f.servicer, bold=True, size=12)
    p.line(f.servicer_address)
    p.line("MORTGAGE STATEMENT", bold=True, size=11, rule=True)
    p.line(f"Statement date: {f.statement_date.isoformat()}")
    p.line(f"Loan number: {f.loan_number}")
    p.line(f"Borrower: {f.borrower}")
    p.line(f"Property address: {f.property_address}", rule=True)
    _pair(p, "Unpaid principal balance", m(f.unpaid_principal_balance))
    _pair(p, "Interest rate", f"{f.interest_rate_pct}%")
    p.line(f"Payment due date: {f.payment_due_date.isoformat()}")
    _pair(p, "Principal and interest", m(f.principal_and_interest))
    _pair(p, "Escrow (taxes and insurance)", m(f.escrow))
    _pair(p, "Monthly payment", m(f.monthly_payment), bold=True)
    _pair(p, "Past due amount", m(f.past_due_amount))
    _pair(p, "Late fees", m(f.late_fees))
    _pair(p, "Total amount due", m(f.total_due), bold=True)
    p.line("Payments past due: " + ", ".join(d.isoformat() for d in f.payments_past_due))
    p.line(f.delinquency_notice)
    p.footer("Page 1 of 1")
    return [p]


def render_application(doc: ApplicationDoc) -> list[Page]:
    f = doc.facts
    p = Page()
    p.line(f.title.upper(), bold=True, size=12, rule=True)
    p.line(f"Borrower: {f.borrower}")
    p.line(f"Mailing address: {f.address}")
    p.line(f"Phone: {f.phone}")
    p.line(f"Loan number: {f.loan_number}")
    p.line(f"Servicer: {f.servicer}")
    p.line(f"Property address: {f.property_address}")
    p.line(f"Occupancy: {f.occupancy}", rule=True)
    p.line("REASON FOR HARDSHIP", bold=True)
    for r in f.hardship_reasons:
        p.line(f"[{'X' if r.checked else ' '}] {r.reason}")
    p.line(f"What do you want to do with the home? {f.intent}", rule=True)
    p.line("MONTHLY INCOME", bold=True)
    _pair(p, "Gross monthly income", m(f.monthly_gross_income))
    _pair(p, "Other income", m(f.other_income))
    p.line("MONTHLY EXPENSES", bold=True, rule=True)
    for e in f.expenses:
        _pair(p, e.category, m(e.amount))
    _pair(p, "Total monthly expenses", m(f.total_expenses), bold=True)
    p.line("ASSETS", bold=True, rule=True)
    for a in f.assets:
        _pair(p, a.description, m(a.amount))
    p.line("Documents enclosed: " + ", ".join(f.enclosed))
    p.line(f"Signature: {f.signature}   Date signed: {f.signed_date.isoformat()}")
    p.footer("Page 1 of 1")
    return [p]


def render_hardship_letter(doc: HardshipLetterDoc) -> list[Page]:
    """The letter's lines are given in the scenario so the quoted lines keep their numbers."""
    p = Page()
    for index, text in enumerate(doc.facts.lines):
        p.line(text, bold=index == 0)
    p.footer("Page 1 of 1")
    return [p]


def render_utility_bill(doc: UtilityBillDoc) -> list[Page]:
    f = doc.facts
    p = Page()
    p.line(f.provider, bold=True, size=12)
    p.line(f.provider_address)
    p.line("UTILITY BILL", bold=True, size=11, rule=True)
    p.line(f"Customer: {f.customer}")
    p.line(f"Service address: {f.service_address}")
    p.line(f"Account ending {f.account_number_last4}")
    p.line(f"Service period: {f.period_start.isoformat()} to {f.period_end.isoformat()}")
    p.line(f"Statement date: {f.statement_date.isoformat()}", rule=True)
    _pair(p, "Amount due", m(f.amount_due), bold=True)
    p.line(f"Due date: {f.due_date.isoformat()}")
    p.footer("Page 1 of 1")
    return [p]

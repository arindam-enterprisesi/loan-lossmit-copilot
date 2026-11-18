"""Bank statement: summary on page 1, transactions with a running balance, a page footer.

``pages_rendered`` can be lower than ``total_pages_printed``: Daniel's August statement
prints "Page 1 of 3" but only two pages exist (the documented defect)."""

from __future__ import annotations

from decimal import Decimal

from synthetic.layout import LEFT, RIGHT, Page, Seg
from synthetic.schema import BankStatementDoc, running_balances, statement_pages
from synthetic.schema import money_text as m


def _table_header(page: Page) -> None:
    page.cols(
        Seg(LEFT, "Date"),
        Seg(120, "Description"),
        Seg(430, "Amount", "r"),
        Seg(RIGHT, "Balance", "r"),
        bold=True,
        rule=True,
    )


def render_bank_statement(doc: BankStatementDoc) -> list[Page]:
    f = doc.facts
    chunks = statement_pages(f)
    if len(chunks) != f.total_pages_printed:
        raise ValueError(
            f"{doc.id}: {len(chunks)} pages of transactions but total_pages_printed="
            f"{f.total_pages_printed}"
        )
    balances = iter(running_balances(f))
    credits = sum((t.amount for t in f.transactions if t.amount > 0), Decimal("0"))
    debits = -sum((t.amount for t in f.transactions if t.amount < 0), Decimal("0"))

    pages: list[Page] = []
    for index, chunk in enumerate(chunks, start=1):
        if index > f.pages_rendered:
            break
        page = Page()
        if index == 1:
            page.line(f.bank, bold=True, size=12)
            page.line(f.bank_address)
            page.line("STATEMENT OF ACCOUNT", bold=True, size=11, rule=True)
            page.line(f"Account holder: {f.account_holder}")
            page.line(f"{f.account_type} ending {f.account_last4}")
            page.line(
                f"Statement period: {f.period_start.isoformat()} to {f.period_end.isoformat()}"
            )
            page.line("ACCOUNT SUMMARY", bold=True, rule=True)
            page.cols(Seg(LEFT, "Opening balance"), Seg(RIGHT, m(f.opening_balance), "r"))
            page.cols(Seg(LEFT, "Total deposits and credits"), Seg(RIGHT, m(credits), "r"))
            page.cols(Seg(LEFT, "Total withdrawals and debits"), Seg(RIGHT, m(debits), "r"))
            page.cols(
                Seg(LEFT, "Closing balance"), Seg(RIGHT, m(f.closing_balance), "r"), bold=True
            )
            page.line("TRANSACTIONS", bold=True, rule=True)
        else:
            page.line(f.bank, bold=True, size=12)
            page.line("STATEMENT OF ACCOUNT (continued)", bold=True, size=11, rule=True)
            page.line(
                f"{f.account_type} ending {f.account_last4}, "
                f"{f.period_start.isoformat()} to {f.period_end.isoformat()}"
            )
        _table_header(page)
        for txn in chunk:
            page.cols(
                Seg(LEFT, txn.date.isoformat()),
                Seg(120, txn.description),
                Seg(430, m(txn.amount), "r"),
                Seg(RIGHT, m(next(balances)), "r"),
            )
        if index == f.total_pages_printed:
            page.cols(Seg(LEFT, "Ending balance"), Seg(RIGHT, m(f.closing_balance), "r"), bold=True)
        page.footer(f"Page {index} of {f.total_pages_printed}")
        pages.append(page)
    return pages

"""Pay stub. Page 1 is laid out so net pay is the 31st line (p1-L31) when the stub has
three earnings and six deductions, as in Daniel Reyes's worked example (Feature Design 1.5)."""

from __future__ import annotations

from synthetic.layout import LEFT, RIGHT, Page, Seg
from synthetic.schema import PayStubDoc
from synthetic.schema import money_text as m


def render_pay_stub(doc: PayStubDoc) -> list[Page]:
    f = doc.facts
    p1 = Page()
    p1.line(f.employer.name, bold=True, size=12)
    p1.line(f.employer.address)
    p1.line(f"EIN {f.employer.ein}")
    p1.line("EARNINGS STATEMENT", bold=True, size=11, rule=True)
    p1.line(f"Employee: {f.employee}")
    p1.line(f"Employee ID: {f.employee_id}")
    p1.line(f"Address: {f.address}")
    p1.line(f"Pay frequency: {f.pay_frequency}")
    p1.line(f"Pay period: {f.period_start.isoformat()} to {f.period_end.isoformat()}")
    p1.line(f"Pay date: {f.pay_date.isoformat()}")
    p1.line(f"Pay period {f.period_number} of {f.periods_per_year}")
    p1.line(f"Direct deposit: account ending {f.direct_deposit_last4}")
    p1.cols(
        Seg(LEFT, "EARNINGS"),
        Seg(250, "Hours", "r"),
        Seg(320, "Rate", "r"),
        Seg(420, "Current", "r"),
        Seg(RIGHT, "Year to date", "r"),
        bold=True,
        rule=True,
    )
    for e in f.earnings:
        p1.cols(
            Seg(LEFT, e.description),
            Seg(250, m(e.hours) if e.hours is not None else "", "r"),
            Seg(320, m(e.rate) if e.rate is not None else "", "r"),
            Seg(420, m(e.current), "r"),
            Seg(RIGHT, m(e.ytd), "r"),
        )
    p1.cols(
        Seg(LEFT, "Gross Pay"),
        Seg(420, m(f.gross_current), "r"),
        Seg(RIGHT, m(f.gross_ytd), "r"),
        bold=True,
        rule=True,
    )
    p1.cols(
        Seg(LEFT, "DEDUCTIONS"),
        Seg(420, "Current", "r"),
        Seg(RIGHT, "Year to date", "r"),
        bold=True,
        rule=True,
    )
    for d in f.deductions:
        p1.cols(Seg(LEFT, d.description), Seg(420, m(d.current), "r"), Seg(RIGHT, m(d.ytd), "r"))
    p1.cols(
        Seg(LEFT, "Total Deductions"),
        Seg(420, m(f.deductions_current), "r"),
        Seg(RIGHT, m(f.deductions_ytd), "r"),
        bold=True,
        rule=True,
    )
    p1.line("PAY SUMMARY", bold=True, rule=True)
    p1.cols(Seg(LEFT, "Gross pay, current period"), Seg(RIGHT, m(f.gross_current), "r"))
    p1.cols(Seg(LEFT, "Less deductions, current period"), Seg(RIGHT, m(f.deductions_current), "r"))
    p1.cols(Seg(LEFT, "Gross pay, year to date"), Seg(RIGHT, m(f.gross_ytd), "r"))
    p1.cols(Seg(LEFT, "Deductions, year to date"), Seg(RIGHT, m(f.deductions_ytd), "r"))
    # The printed amount can differ from the true one: that is the documented defect.
    printed = f.printed_net_current if f.printed_net_current is not None else f.net_current
    p1.cols(Seg(LEFT, "Net Pay"), Seg(RIGHT, m(printed), "r"), bold=True)
    p1.cols(Seg(LEFT, "Net pay, year to date"), Seg(RIGHT, m(f.net_ytd), "r"))
    p1.line("Questions about this statement? Contact Payroll, (614) 555-0182.")
    p1.footer(f"Page 1 of {f.pages}")
    pages = [p1]

    if f.pages >= 2:
        p2 = Page()
        p2.line(f.employer.name, bold=True, size=12)
        p2.line("EARNINGS STATEMENT (continued)", bold=True, size=11, rule=True)
        p2.line(f"Employee: {f.employee}")
        p2.line(f"Pay date: {f.pay_date.isoformat()}")
        p2.line("YEAR-TO-DATE SUMMARY", bold=True, rule=True)
        for e in f.earnings:
            p2.cols(Seg(LEFT, f"{e.description}, year to date"), Seg(RIGHT, m(e.ytd), "r"))
        for d in f.deductions:
            p2.cols(Seg(LEFT, f"{d.description}, year to date"), Seg(RIGHT, m(d.ytd), "r"))
        p2.cols(Seg(LEFT, "Gross pay, year to date"), Seg(RIGHT, m(f.gross_ytd), "r"), bold=True)
        p2.cols(Seg(LEFT, "Net pay, year to date"), Seg(RIGHT, m(f.net_ytd), "r"), bold=True)
        p2.line(f"Pay periods elapsed this year: {f.period_number} of {f.periods_per_year}")
        p2.line("Employer message: open enrollment begins November 1.")
        p2.footer(f"Page 2 of {f.pages}")
        pages.append(p2)
    return pages

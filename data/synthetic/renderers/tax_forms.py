"""Form W-2 and Form 1040."""

from __future__ import annotations

from synthetic.layout import LEFT, RIGHT, Page, Seg
from synthetic.schema import Form1040Doc, W2Doc
from synthetic.schema import money_text as m


def _box(page: Page, label: str, amount: str) -> None:
    page.cols(Seg(LEFT, label), Seg(RIGHT, amount, "r"))


def render_w2(doc: W2Doc) -> list[Page]:
    f = doc.facts
    p = Page()
    p.line(f"Form W-2  Wage and Tax Statement  {f.tax_year}", bold=True, size=12, rule=True)
    p.line("Copy B - To Be Filed With Employee's FEDERAL Tax Return")
    p.line(f"a  Employee's social security number: XXX-XX-{f.ssn_last4}")
    p.line(f"b  Employer identification number (EIN): {f.employer.ein}")
    p.line(f"c  Employer's name: {f.employer.name}")
    p.line(f"c  Employer's address: {f.employer.address}")
    p.line(f"e  Employee's name: {f.employee}")
    p.line(f"f  Employee's address: {f.address}", rule=True)
    _box(p, "1  Wages, tips, other compensation", m(f.box1))
    _box(p, "2  Federal income tax withheld", m(f.box2))
    _box(p, "3  Social security wages", m(f.box3))
    _box(p, "4  Social security tax withheld", m(f.box4))
    _box(p, "5  Medicare wages and tips", m(f.box5))
    _box(p, "6  Medicare tax withheld", m(f.box6))
    for index, item in enumerate(f.box12):
        _box(p, f"12{'abcd'[index]}  Code {item.code}", m(item.amount))
    p.footer("Page 1 of 1")
    return [p]


def render_form_1040(doc: Form1040Doc) -> list[Page]:
    f = doc.facts
    p = Page()
    p.line(
        f"Form 1040  U.S. Individual Income Tax Return  {f.tax_year}", bold=True, size=12, rule=True
    )
    p.line(f"Filing status: {f.filing_status}")
    p.line(f"Taxpayer: {f.taxpayer}   SSN XXX-XX-{f.ssn_last4}")
    p.line(f"Address: {f.address}", rule=True)
    p.line("INCOME", bold=True)
    _box(p, "1a  Total amount from Form(s) W-2, box 1 (wages)", m(f.wages))
    _box(p, "2b  Taxable interest", m(f.taxable_interest))
    _box(p, "9   Total income", m(f.total_income))
    _box(p, "10  Adjustments to income", m(f.adjustments))
    _box(p, "11  Adjusted gross income", m(f.adjusted_gross_income))
    p.footer("Page 1 of 1")
    return [p]

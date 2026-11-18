# ruff: noqa: I001
"""The known defects and documented line IDs are really in the rendered documents."""

from __future__ import annotations

import re

from tests.data.conftest import Rendered
from tests.data.helpers import D, read_pages
from synthetic.schema import Scenario, statement_pages

AMOUNT = re.compile(r"-?\d[\d,]*\.\d{2}")


def amount(line: str) -> D:
    return D(AMOUNT.findall(line)[-1].replace(",", ""))


def test_daniel_stub_prints_net_pay_2083_61_on_line_p1_l31(
    rendered: Rendered, daniel: Scenario
) -> None:
    pages = read_pages(rendered.path("daniel_reyes/pay_stub_2026-09-27.pdf"))
    line_31 = pages[0][30]  # p1-L31 (Feature Design 1.5)
    assert line_31 == "Net Pay 2,083.61"
    defect = next(d for d in daniel.defects if d["id"] == "net_pay_misprint")
    assert defect["line"] == "p1-L31"
    assert (defect["printed"], defect["true"]) == ("2083.61", "2033.61")


def test_only_the_arithmetic_catches_the_misprint(rendered: Rendered) -> None:
    lines = read_pages(rendered.path("daniel_reyes/pay_stub_2026-09-27.pdf"))[0]
    gross = amount(next(x for x in lines if x.startswith("Gross pay, current period")))
    deductions = amount(next(x for x in lines if x.startswith("Less deductions, current period")))
    printed = amount(lines[30])
    assert (gross, deductions) == (D("3070.50"), D("1036.89"))
    assert gross - deductions == D("2033.61")
    assert printed == D("2083.61") != gross - deductions
    assert printed - (gross - deductions) == D("50.00")
    # The misprint is genuinely in the text (an OCR-style misread, not a missing value), and
    # the money that reached the bank is the true net pay.
    statement = "\n".join(
        "\n".join(p) for p in read_pages(rendered.path("daniel_reyes/bank_statement_2026-09.pdf"))
    )
    assert "CEDAR VALLEY MFG PAYROLL 2,033.61" in statement
    assert "2,083.61" not in statement


def test_august_statement_says_page_1_of_3_but_has_two_pages(
    rendered: Rendered, daniel: Scenario
) -> None:
    pages = read_pages(rendered.path("daniel_reyes/bank_statement_2026-08.pdf"))
    assert len(pages) == 2
    assert pages[0][-2] == "Page 1 of 3" and pages[1][-2] == "Page 2 of 3"
    assert not any("Page 3" in line for page in pages for line in page)
    facts = daniel.document("bank_statement_2026-08").facts
    assert (facts.total_pages_printed, facts.pages_rendered) == (3, 2)
    # the missing page held real transactions, so the visible rows stop short of the closing balance
    third = statement_pages(facts)[2]
    shown = sum(t.amount for page in statement_pages(facts)[:2] for t in page)
    assert facts.opening_balance + shown != facts.closing_balance
    assert facts.closing_balance - (facts.opening_balance + shown) == sum(t.amount for t in third)
    assert "Ending balance" not in "\n".join("\n".join(p) for p in pages)


def test_september_statement_is_complete_and_holds_the_2000_transfer(rendered: Rendered) -> None:
    pages = read_pages(rendered.path("daniel_reyes/bank_statement_2026-09.pdf"))
    assert [p[-2] for p in pages] == ["Page 1 of 3", "Page 2 of 3", "Page 3 of 3"]
    text = "\n".join("\n".join(p) for p in pages)
    assert "2026-09-22 ZELLE FROM PATRICIA OWENS REF 8841 2,000.00" in text
    assert "Ending balance 9,226.32" in text


def test_hardship_letter_quotes_sit_on_the_documented_lines(
    rendered: Rendered, angela: Scenario
) -> None:
    lines = read_pages(rendered.path("angela_whitfield/hardship_letter.pdf"))[0]
    quotes = angela.document("hardship_letter").facts.quotes
    reason, intent = quotes["primary_reason"], quotes["intent"]
    assert "cut my hours from 40 to 30 a week in July" in lines[5]  # p1-L6
    assert "I want to keep my home" in lines[13]  # p1-L14
    assert (reason.line, intent.line) == (6, 14)
    assert lines.count(lines[5]) == 1 and lines.count(lines[13]) == 1


def test_daniels_case_is_missing_the_2024_documents_on_purpose(
    rendered: Rendered, daniel: Scenario
) -> None:
    in_case = {p.name for p in rendered.path("daniel_reyes").glob("*.pdf")}
    held_back = {p.name for p in rendered.path("daniel_reyes/withheld").glob("*.pdf")}
    assert held_back == {"w2_2024.pdf", "form_1040_2024.pdf"}
    assert not (in_case & held_back)
    assert len(in_case) == 7
    withheld_ids = [d.id for d in daniel.documents if d.role == "withheld"]
    assert sorted(withheld_ids) == ["form_1040_2024", "w2_2024"]
    # the withheld W-2 still carries the figures the income trend needs
    w2_2024 = "\n".join(
        "\n".join(p) for p in read_pages(rendered.path("daniel_reyes/withheld/w2_2024.pdf"))
    )
    assert "70,431.80" in w2_2024


def test_angelas_case_has_no_august_statement(rendered: Rendered) -> None:
    names = {p.name for p in rendered.path("angela_whitfield").glob("*.pdf")}
    assert "bank_statement_2026-07.pdf" in names and "bank_statement_2026-09.pdf" in names
    assert not any("2026-08" in n for n in names)
    assert len(names) == 8


def test_mislabelled_upload_is_recorded_in_the_manifest(rendered: Rendered) -> None:
    entry = rendered.entry("daniel_reyes/bank_statement_2026-09.pdf")
    assert (entry["doc_type"], entry["declared_type"]) == ("bank_statement", "tax_return_1040")
    assert rendered.entry("daniel_reyes/bank_statement_2026-08.pdf")["declared_type"] is None

"""One renderer per document type: facts in, pages of text rows out."""

from __future__ import annotations

from synthetic.layout import Page
from synthetic.renderers.bank_statement import render_bank_statement
from synthetic.renderers.credit_report import render_credit_report
from synthetic.renderers.other_docs import (
    render_application,
    render_hardship_letter,
    render_mortgage_statement,
    render_utility_bill,
)
from synthetic.renderers.pay_stub import render_pay_stub
from synthetic.renderers.tax_forms import render_form_1040, render_w2
from synthetic.schema import Document


def render_pages(doc: Document) -> list[Page]:
    match doc.type:
        case "pay_stub":
            return render_pay_stub(doc)
        case "bank_statement":
            return render_bank_statement(doc)
        case "w2":
            return render_w2(doc)
        case "tax_return_1040":
            return render_form_1040(doc)
        case "credit_report":
            return render_credit_report(doc)
        case "mortgage_statement":
            return render_mortgage_statement(doc)
        case "mortgage_assistance_application":
            return render_application(doc)
        case "hardship_letter":
            return render_hardship_letter(doc)
        case "expense_bill":
            return render_utility_bill(doc)
    raise ValueError(f"no renderer for {doc.type}")  # pragma: no cover

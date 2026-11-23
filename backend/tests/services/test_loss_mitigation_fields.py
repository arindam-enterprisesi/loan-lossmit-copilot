"""The fields the loss-mitigation budget and the credit analysis read from documents.

Arindam's extract schemas already return the mortgage assistance application (stated income,
expenses, assets) and the mortgage statement (arrears, payment parts). The pipeline stores any field
it is given as plain text, so these tests pin what ``config/document_fields.yaml`` adds: the right
kind (amount, date), a stable name for every repeating row, and no "required" fields, so a reader
that misses one raises no new flags on the demo documents.

The credit report has no extract schema yet. Its tradeline fields are defined here ahead of it,
under the exact names that schema must produce (see docs/build-log.md), so Feature 3 can read a
credit report's debts as soon as one is extracted.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from app.llm.samples import load_lines
from app.prompts.schemas.documents import (
    MortgageAssistanceApplicationFields,
    MortgageStatementFields,
)
from app.services.doc_lines import DocLine
from app.services.extraction import prepare_fields
from tests.services.test_llm_extractor import CFG, blank, extractor_for, fv


def application_lines() -> list[DocLine]:
    return [DocLine(ln.page, ln.line, ln.text) for ln in load_lines("angela_application")]


def angela_application_reply() -> dict[str, Any]:
    fields = blank(MortgageAssistanceApplicationFields)
    fields.update(
        borrower_names=fv("Angela Whitfield", "p1-L2"),
        loan_number=fv("8800412271", "p1-L5"),
        property_address=fv("2210 Larkspur Court, Dayton, OH 45420", "p1-L7"),
        occupancy=fv("Owner-occupied primary residence", "p1-L8"),
        hardship_reasons=[{"reason": fv("Reduction in income", "p1-L10")}],
        intent=fv("Keep the home", "p1-L16"),
        monthly_income=[
            {
                "description": fv("Gross monthly income", "p1-L18"),
                "amount": fv("4,200.00", "p1-L18"),
            },
            {"description": fv("Other income", "p1-L19"), "amount": fv("0.00", "p1-L19")},
        ],
        monthly_expenses=[
            {"description": fv("Housing (mortgage)", "p1-L21"), "amount": fv("1,720.00", "p1-L21")},
            {"description": fv("Utilities", "p1-L22"), "amount": fv("310.00", "p1-L22")},
            {"description": fv("Food and everyday", "p1-L23"), "amount": fv("780.00", "p1-L23")},
            {"description": fv("Loan payments", "p1-L24"), "amount": fv("410.00", "p1-L24")},
            {"description": fv("Other", "p1-L25"), "amount": fv("200.00", "p1-L25")},
        ],
        total_monthly_expenses=fv("3,420.00", "p1-L26"),
        assets=[
            {"description": fv("Checking account", "p1-L28"), "amount": fv("640.25", "p1-L28")}
        ],
        signed_date=fv("2026-10-14", "p1-L30"),
    )
    return {"fields": fields, "signals": []}


async def read_application() -> Any:
    extractor, _ = extractor_for(angela_application_reply())
    return await extractor.extract("mortgage_assistance_application", application_lines())


# --- the application ------------------------------------------------------------------------


async def test_the_application_is_flattened_into_numbered_rows_with_stable_names() -> None:
    outcome = await read_application()

    got = {name: f.value for name, f in outcome.fields.items()}

    assert got["borrower_names"] == "Angela Whitfield"
    assert got["hardship_reasons_001_reason"] == "Reduction in income"
    assert (got["monthly_income_001_description"], got["monthly_income_001_amount"]) == (
        "Gross monthly income",
        "4,200.00",
    )
    assert got["monthly_expenses_005_description"] == "Other"
    assert got["monthly_expenses_005_amount"] == "200.00"
    assert got["assets_001_amount"] == "640.25"
    assert got["total_monthly_expenses"] == "3,420.00"
    assert outcome.fields["monthly_expenses_005_amount"].lines == ["p1-L25"]  # rule 2: its line


async def test_the_application_fields_have_the_right_kinds_and_normal_forms() -> None:
    outcome = await read_application()

    prepared = {f.name: f for f in prepare_fields("mortgage_assistance_application", outcome, CFG)}

    assert prepared["monthly_expenses_001_amount"].kind == "amount"
    assert prepared["monthly_expenses_001_amount"].normalized == "1720.00"
    assert prepared["monthly_income_001_amount"].normalized == "4200.00"
    assert prepared["total_monthly_expenses"].normalized == "3420.00"
    assert prepared["assets_001_amount"].normalized == "640.25"
    assert (prepared["signed_date"].kind, prepared["signed_date"].normalized) == (
        "date",
        "2026-10-14",
    )
    assert prepared["monthly_expenses_001_description"].kind == "text"
    assert prepared["hardship_reasons_001_reason"].kind == "text"


async def test_the_owner_of_the_application_is_the_borrower_named_on_it() -> None:
    assert CFG.types["mortgage_assistance_application"].borrower_field == "borrower_names"


# --- the mortgage statement -----------------------------------------------------------------


async def test_the_mortgage_statement_arrears_and_payment_parts_are_typed() -> None:
    fields = blank(MortgageStatementFields)
    fields.update(
        servicer=fv("Pinebrook Mortgage Servicing", "p1-L1"),
        borrower_names=fv("Angela Whitfield", "p1-L2"),
        loan_number=fv("8800412271", "p1-L3"),
        statement_date=fv("2026-10-16", "p1-L4"),
        unpaid_principal_balance=fv("212,400.00", "p1-L5"),
        principal_and_interest=fv("1,298.40", "p1-L6"),
        escrow=fv("421.60", "p1-L7"),
        regular_monthly_payment=fv("1,720.00", "p1-L8"),
        past_due_amount=fv("5,160.00", "p1-L9"),
    )
    lines = [
        DocLine(1, 1, "Pinebrook Mortgage Servicing"),
        DocLine(1, 2, "Angela Whitfield"),
        DocLine(1, 3, "Loan number 8800412271"),
        DocLine(1, 4, "Statement date 2026-10-16"),
        DocLine(1, 5, "Unpaid principal balance 212,400.00"),
        DocLine(1, 6, "Principal and interest 1,298.40"),
        DocLine(1, 7, "Escrow 421.60"),
        DocLine(1, 8, "Regular monthly payment 1,720.00"),
        DocLine(1, 9, "Past due amount 5,160.00"),
    ]
    extractor, _ = extractor_for({"fields": fields, "signals": []})

    outcome = await extractor.extract("mortgage_statement", lines)
    prepared = {f.name: f for f in prepare_fields("mortgage_statement", outcome, CFG)}

    assert prepared["past_due_amount"].kind == "amount"
    assert prepared["past_due_amount"].normalized == "5160.00"
    assert prepared["regular_monthly_payment"].normalized == "1720.00"
    assert prepared["unpaid_principal_balance"].normalized == "212400.00"
    assert (prepared["statement_date"].kind, prepared["statement_date"].normalized) == (
        "date",
        "2026-10-16",
    )
    assert CFG.types["mortgage_statement"].borrower_field == "borrower_names"


# --- the credit report (fields defined ahead of its schema) ----------------------------------


@pytest.mark.parametrize(
    ("name", "kind"),
    [
        ("tradeline_001_creditor", "text"),
        ("tradeline_002_account_type", "text"),
        ("tradeline_003_balance", "amount"),
        ("tradeline_004_credit_limit", "amount"),
        ("tradeline_005_monthly_payment", "amount"),
    ],
)
def test_a_credit_reports_tradelines_are_numbered_rows_of_typed_parts(name: str, kind: str) -> None:
    assert CFG.kind_of("credit_report", name) == kind
    assert CFG.row_match("credit_report", name) is not None


def test_the_credit_report_names_its_consumer_and_date() -> None:
    names = {f.name for f in CFG.types["credit_report"].fields}
    assert {"consumer_name", "report_date"} <= names
    assert CFG.types["credit_report"].borrower_field == "consumer_name"


@pytest.mark.parametrize(
    "doc_type", ["mortgage_assistance_application", "mortgage_statement", "credit_report"]
)
def test_none_of_these_fields_is_required(doc_type: str) -> None:
    # A reader that cannot read one of these types (the rule-based fake, or a credit report with no
    # schema yet) must not start raising "not found" warnings on documents that were quiet before.
    assert CFG.required_fields(doc_type) == []


def test_the_shipped_example_replies_are_valid_json() -> None:
    # Guards the helpers above: a reply the extract schema rejects would fail every test quietly.
    assert json.loads(json.dumps(angela_application_reply()))["fields"]["total_monthly_expenses"]

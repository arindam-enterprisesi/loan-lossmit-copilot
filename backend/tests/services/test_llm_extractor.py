"""LlmExtractor: Arindam's real extract task, run through his gateway with a fake provider.

Nothing here calls a model. A canned reply goes in, ``app.llm.tasks.extract`` validates it against
his schema, and the adapter flattens it into the indexed fields the checks and the income analysis
read. Daniel's pay stub must still raise the net pay check (3,070.50 - 1,036.89 = 2,033.61, not the
printed 2,083.61) when it arrives through this path.
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from pydantic import BaseModel

from app.llm.config import ExtractionSettings
from app.llm.gateway import Gateway
from app.llm.samples import load_lines
from app.llm.types import AdapterResponse
from app.prompts.schemas.documents import BankStatementFields, PayStubFields
from app.prompts.schemas.fields import ExtractedField as SchemaField
from app.services.doc_lines import DocLine, printed_page_label
from app.services.document_config import get_document_fields, get_validation_config
from app.services.extraction import prepare_fields, prepared_to_inputs
from app.services.extractor import LlmExtractor
from app.services.validation import LineInput, PageInput, ValidationInput, validate
from tests.llm.fakes import FakeAdapter, fake_config

CFG = get_document_fields()
RULES = get_validation_config()


# --- canned replies -------------------------------------------------------------------------


def fv(value: str | None, *lines: str, certainty: str = "high") -> dict[str, Any]:
    if value is None:
        return {"value": None, "lines": [], "certainty": "low"}
    return {"value": value, "lines": list(lines), "certainty": certainty}


def blank(model: type[BaseModel]) -> dict[str, Any]:
    """A reply with every field null and every repeating group empty."""
    return {
        name: fv(None) if info.annotation is SchemaField else []
        for name, info in model.model_fields.items()
    }


def daniel_pay_stub_reply() -> dict[str, Any]:
    fields = blank(PayStubFields)
    fields.update(
        employer_name=fv("Cedar Valley Manufacturing, Inc.", "p1-L1"),
        employee_name=fv("Daniel Reyes", "p1-L5"),
        pay_frequency=fv("Biweekly", "p1-L8"),
        pay_period_start=fv("2026-09-14", "p1-L9"),
        pay_period_end=fv("2026-09-27", "p1-L9"),
        pay_date=fv("2026-10-02", "p1-L10"),
        earnings=[
            {
                "description": fv("Regular", "p1-L14"),
                "hours": fv("80.00", "p1-L14"),
                "rate": fv("34.50", "p1-L14"),
                "current": fv("2,760.00", "p1-L14"),
                "ytd": fv("52,440.00", "p1-L14"),
            },
            {
                "description": fv("Overtime 1.5x", "p1-L15"),
                "hours": fv("3.96", "p1-L15"),
                "rate": fv("51.75", "p1-L15"),
                "current": fv("204.93", "p1-L15"),
                "ytd": fv("3,897.10", "p1-L15"),
            },
            {
                "description": fv("Bonus", "p1-L16"),
                "hours": fv(None),
                "rate": fv(None),
                "current": fv("105.57", "p1-L16"),
                "ytd": fv("2,002.40", "p1-L16"),
            },
        ],
        gross_pay_current=fv("3,070.50", "p1-L17", "p1-L27"),
        gross_pay_ytd=fv("58,339.50", "p1-L17", "p1-L29"),
        total_deductions_current=fv("1,036.89", "p1-L25"),
        total_deductions_ytd=fv("19,700.91", "p1-L25"),
        net_pay_current=fv("2,083.61", "p1-L31", certainty="medium"),
        net_pay_ytd=fv("38,638.59", "p1-L32", "p2-L16"),
    )
    return {"fields": fields, "signals": []}


def statement_reply(transactions: list[dict[str, Any]]) -> dict[str, Any]:
    fields = blank(BankStatementFields)
    fields.update(
        institution=fv("Fairhaven Community Bank", "p1-L1"),
        account_holder=fv("Daniel Reyes", "p1-L4"),
        account_number=fv("Checking ending 6032", "p1-L5"),
        statement_period_start=fv("2026-08-01", "p1-L6"),
        statement_period_end=fv("2026-08-31", "p1-L6"),
        opening_balance=fv("5,845.26", "p1-L8"),
        closing_balance=fv("6,455.13", "p1-L9"),
        transactions=transactions,
    )
    return {"fields": fields, "signals": []}


def row(date: str, description: str, amount: str, column: str | None, ref: str) -> dict[str, Any]:
    return {
        "date": fv(date, ref),
        "description": fv(description, ref),
        "amount": fv(amount, ref),
        "column": fv(column, ref),
        "balance": fv(None),
    }


def extractor_for(*replies: dict[str, Any]) -> tuple[LlmExtractor, FakeAdapter]:
    adapter = FakeAdapter(
        [AdapterResponse(text=json.dumps(r), input_tokens=900, output_tokens=400) for r in replies]
    )
    config = fake_config().model_copy(
        update={"extraction": ExtractionSettings(max_pages_per_call=4)}
    )
    return LlmExtractor(gateway=Gateway({"fake": adapter}, config), config=CFG), adapter


def stub_lines() -> list[DocLine]:
    return [DocLine(ln.page, ln.line, ln.text) for ln in load_lines("daniel_pay_stub")]


# --- the flattened fields -------------------------------------------------------------------


async def test_daniels_pay_stub_is_flattened_into_indexed_fields() -> None:
    extractor, adapter = extractor_for(daniel_pay_stub_reply())
    outcome = await extractor.extract("pay_stub", stub_lines())

    assert (outcome.provider, outcome.model, outcome.prompt_id) == (
        "fake",
        "fake-model",
        "extract@1",
    )
    got = {name: f.value for name, f in outcome.fields.items()}
    assert got["earnings_001_description"] == "Regular"
    assert (got["earnings_001_hours"], got["earnings_001_rate"]) == ("80.00", "34.50")
    assert (got["earnings_001_current"], got["earnings_001_ytd"]) == ("2,760.00", "52,440.00")
    assert got["earnings_002_description"] == "Overtime 1.5x"
    assert got["earnings_003_current"] == "105.57"
    assert "earnings_003_hours" not in got  # a null is left out, not stored as an empty value
    assert got["pay_frequency"] == "Biweekly"
    assert got["net_pay_current"] == "2,083.61"
    assert outcome.fields["net_pay_current"].lines == ["p1-L31"]
    assert outcome.fields["net_pay_current"].certainty == "medium"
    assert len(adapter.requests) == 1  # one call for a two-page document


async def test_the_flattened_fields_have_the_right_kinds_and_normal_forms() -> None:
    extractor, _ = extractor_for(daniel_pay_stub_reply())
    outcome = await extractor.extract("pay_stub", stub_lines())
    prepared = {f.name: f for f in prepare_fields("pay_stub", outcome, CFG)}

    assert (prepared["earnings_001_hours"].kind, prepared["earnings_001_hours"].normalized) == (
        "number",
        "80.00",
    )
    assert prepared["earnings_001_rate"].normalized == "34.50"
    assert prepared["earnings_001_current"].normalized == "2760.00"
    assert prepared["earnings_002_ytd"].normalized == "3897.10"
    assert prepared["earnings_001_description"].kind == "text"
    assert prepared["pay_period_end"].normalized == "2026-09-27"
    # The value as read is kept, and the first normalised form is the original.
    assert prepared["net_pay_current"].value == "2,083.61"
    assert prepared["net_pay_current"].original == "2083.61"
    # Required fields the reader did not return still get an empty row for a person to fill in.
    assert "employer_name" in prepared and prepared["employer_name"].value is not None


async def test_daniels_stub_still_raises_only_the_net_pay_check_through_the_real_path() -> None:
    extractor, _ = extractor_for(daniel_pay_stub_reply())
    lines = stub_lines()
    outcome = await extractor.extract("pay_stub", lines)
    inputs = prepared_to_inputs("pay_stub", prepare_fields("pay_stub", outcome, CFG))
    pages = sorted({ln.page for ln in lines})
    inp = ValidationInput(
        "pay_stub",
        inputs,
        {ln.ref: LineInput(ln.ref, ln.text) for ln in lines},
        [PageInput(p, printed_page_label(ln.text for ln in lines if ln.page == p)) for p in pages],
        outcome.signals,
    )
    report = validate(inp, RULES, CFG)

    net = [f for f in report.findings if f.code == "DI-CHK-02"]
    assert len(net) == 1 and net[0].field == "net_pay_current"
    assert "2,033.61" in net[0].message and "2,083.61" in net[0].message
    assert [f.code for f in report.findings if f.marks_review] == ["DI-CHK-02"]


# --- masking, names, signs ------------------------------------------------------------------


async def test_the_account_number_is_renamed_and_cut_to_its_last_four() -> None:
    extractor, _ = extractor_for(statement_reply([]))
    outcome = await extractor.extract("bank_statement", [DocLine(1, 1, "STATEMENT OF ACCOUNT")])
    assert "account_number" not in outcome.fields and "institution" not in outcome.fields
    assert outcome.fields["institution_name"].value == "Fairhaven Community Bank"

    prepared = {f.name: f for f in prepare_fields("bank_statement", outcome, CFG)}
    account = prepared["account_last4"]
    assert (account.value, account.normalized, account.original) == ("6032", "6032", "6032")
    assert "Checking" not in str(account) and "ending" not in str(account)


async def test_amounts_in_deposit_and_withdrawal_columns_are_signed_by_the_heading() -> None:
    reply = statement_reply(
        [
            row("2026-08-01", "OAKMONT APARTMENTS RENT", "1,425.00", "Withdrawals", "p1-L12"),
            row("2026-08-07", "CEDAR VALLEY MFG PAYROLL", "2,033.61", "Deposits", "p1-L13"),
            row("2026-08-09", "UNKNOWN COLUMN", "10.00", "Memo", "p1-L14"),
        ]
    )
    extractor, _ = extractor_for(reply)
    outcome = await extractor.extract("bank_statement", [DocLine(1, 1, "x")])

    assert outcome.fields["txn_001_amount"].sign == "-"
    assert outcome.fields["txn_002_amount"].sign == "+"
    assert outcome.fields["txn_003_amount"].sign is None  # a heading it does not know: no guess
    assert outcome.fields["txn_001_column"].value == "Withdrawals"

    prepared = {f.name: f for f in prepare_fields("bank_statement", outcome, CFG)}
    assert prepared["txn_001_amount"].value == "1,425.00"  # as printed
    assert prepared["txn_001_amount"].normalized == "-1425.00"  # the sign comes from the column
    assert prepared["txn_002_amount"].normalized == "2033.61"
    assert prepared["txn_003_amount"].normalized == "10.00"


async def test_a_column_signed_amount_is_found_in_its_line_despite_the_sign() -> None:
    reply = statement_reply(
        [row("2026-08-01", "OAKMONT APARTMENTS RENT", "1,425.00", "Withdrawals", "p1-L12")]
    )
    extractor, _ = extractor_for(reply)
    outcome = await extractor.extract("bank_statement", [DocLine(1, 1, "x")])
    inputs = prepared_to_inputs("bank_statement", prepare_fields("bank_statement", outcome, CFG))
    lines = {"p1-L12": LineInput("p1-L12", "2026-08-01 OAKMONT APARTMENTS RENT 1,425.00")}
    report = validate(ValidationInput("bank_statement", inputs, lines, [], []), RULES, CFG)
    flagged = {f.field for f in report.findings if f.code == "DI-W601"}
    assert "txn_001_amount" not in flagged  # the page prints 1,425.00 with no minus sign


# --- signals, types without a schema --------------------------------------------------------


async def test_signals_become_plain_notes() -> None:
    reply = daniel_pay_stub_reply()
    reply["signals"] = [
        {"kind": "cut_off_table", "detail": "the earnings table is cut off", "lines": ["p1-L14"]}
    ]
    extractor, _ = extractor_for(reply)
    outcome = await extractor.extract("pay_stub", stub_lines())
    assert outcome.signals == ["the earnings table is cut off"]


@pytest.mark.parametrize("doc_type", ["credit_report", "hardship_letter", "unrecognized"])
async def test_types_without_a_field_schema_make_no_model_call(doc_type: str) -> None:
    extractor, adapter = extractor_for()
    outcome = await extractor.extract(doc_type, [DocLine(1, 1, "anything")])
    assert outcome.fields == {} and outcome.signals == []
    assert (outcome.provider, outcome.model) == ("none", "none")  # never mistaken for a model
    assert adapter.requests == []

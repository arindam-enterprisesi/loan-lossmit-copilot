"""The rule-based reader, the type decision, and the seam: all on the generated documents.

These run the fake reader and then the real checks over the PDFs ``data/synthetic`` generates, so
the documented defects show up exactly as the Feature Design says: Daniel's net pay (FD 1.8), the
August statement's missing page, and a statement uploaded as a tax return.
"""

from __future__ import annotations

import logging
from types import SimpleNamespace
from typing import Any

import pytest

from app.services import classification, extractor
from app.services.classification import (
    Classification,
    LlmClassifier,
    PipelineUnavailableError,
    decide_type,
    get_classifier,
)
from app.services.doc_lines import DocLine, printed_page_label
from app.services.document_config import get_document_fields, get_validation_config
from app.services.extraction import prepare_fields, prepared_to_inputs
from app.services.extractor import LlmExtractor, get_extractor
from app.services.fake_reader import FakeClassifier, FakeExtractor
from app.services.validation import (
    LineInput,
    PageInput,
    ValidationInput,
    ValidationReport,
    validate,
)
from tests.conftest import Rendered
from tests.data.helpers import read_pages

CFG = get_document_fields()
RULES = get_validation_config()
STUB = "daniel_reyes/pay_stub_2026-09-27.pdf"
AUGUST = "daniel_reyes/bank_statement_2026-08.pdf"
SEPTEMBER = "daniel_reyes/bank_statement_2026-09.pdf"


def lines_of(rendered: Rendered, path: str) -> tuple[list[DocLine], list[list[str]]]:
    pages = read_pages(rendered.path(path))
    lines = [DocLine(p, n, t) for p, rows in enumerate(pages, 1) for n, t in enumerate(rows, 1)]
    return lines, pages


async def check(rendered: Rendered, path: str) -> tuple[Any, ValidationReport]:
    """Classify, extract and validate one generated document, as the pipeline will."""
    lines, pages = lines_of(rendered, path)
    cls = await FakeClassifier().classify(lines)
    outcome = await FakeExtractor().extract(cls.doc_type, lines)
    inputs = prepared_to_inputs(cls.doc_type, prepare_fields(cls.doc_type, outcome, CFG))
    inp = ValidationInput(
        cls.doc_type,
        inputs,
        {ln.ref: LineInput(ln.ref, ln.text) for ln in lines},
        [PageInput(i, printed_page_label(rows)) for i, rows in enumerate(pages, 1)],
        outcome.signals,
    )
    return outcome, validate(inp, RULES, CFG)


def review_codes(report: ValidationReport) -> set[str]:
    return {f.code for f in report.findings if f.marks_review}


# --- classify -------------------------------------------------------------------------------


async def test_every_generated_document_is_classified_to_its_manifest_type(
    rendered: Rendered,
) -> None:
    pdfs = [f for f in rendered.manifest["files"] if f["role"] in {"case", "withheld"}]
    assert len(pdfs) == 17
    for entry in pdfs:
        lines, _ = lines_of(rendered, entry["path"])
        result = await FakeClassifier().classify(lines)
        assert result.doc_type == entry["doc_type"], entry["path"]
        assert result.certainty == "high" and result.justification_line_ids, entry["path"]
        assert (result.provider, result.model) == ("fake", "rule-based-v1")
        refs = {ln.ref for ln in lines}
        assert set(result.justification_line_ids) <= refs and result.unknown_line_ids == []


async def test_text_that_matches_nothing_is_unrecognized_with_low_certainty() -> None:
    lines = [DocLine(1, 1, "Weekly newsletter"), DocLine(1, 2, "Lunch menu inside")]
    result = await FakeClassifier().classify(lines)
    assert (result.doc_type, result.certainty, result.justification_line_ids) == (
        "unrecognized",
        "low",
        [],
    )


async def test_only_the_first_two_pages_are_read_like_the_real_task() -> None:
    lines = [DocLine(1, 1, "Weekly newsletter"), DocLine(3, 1, "EARNINGS STATEMENT")]
    assert (await FakeClassifier().classify(lines)).doc_type == "unrecognized"


async def test_the_file_name_is_never_an_input() -> None:
    # classify() receives lines only: a file called w2.pdf that holds a bank statement is a bank
    # statement (FSD 4.2). There is no name parameter to misuse.
    lines = [DocLine(1, 1, "STATEMENT OF ACCOUNT")]
    assert (await FakeClassifier().classify(lines)).doc_type == "bank_statement"


# --- extract and check: the documented defects -----------------------------------------------


async def test_daniels_stub_is_read_as_printed_and_only_the_net_pay_check_fails(
    rendered: Rendered,
) -> None:
    outcome, report = await check(rendered, STUB)

    net = outcome.fields["net_pay_current"]
    assert (net.value, net.lines) == ("2,083.61", ["p1-L31"])  # the misprint, with its line
    assert outcome.fields["gross_pay_current"].lines == ["p1-L17"]
    assert outcome.fields["total_deductions_current"].lines == ["p1-L25"]
    assert (outcome.provider, outcome.model, outcome.prompt_id) == (
        "fake",
        "rule-based-v1",
        "fake-extract@1",
    )
    assert review_codes(report) == {"DI-CHK-02"}
    [flag] = [f for f in report.findings if f.code == "DI-CHK-02"]
    assert flag.message == "Gross 3,070.50 minus deductions 1,036.89 is 2,033.61, not 2,083.61."
    assert (flag.field, flag.lines) == ("net_pay_current", ("p1-L17", "p1-L25", "p1-L31"))


async def test_the_stub_earnings_add_up_to_gross(rendered: Rendered) -> None:
    outcome, report = await check(rendered, STUB)
    earnings = {n: f.value for n, f in outcome.fields.items() if n.startswith("earnings_")}
    assert earnings == {
        "earnings_regular_current": "2,760.00",
        "earnings_overtime_current": "204.93",
        "earnings_bonus_current": "105.57",
    }
    assert "DI-CHK-01" not in review_codes(report)  # 2,760.00 + 204.93 + 105.57 = 3,070.50


async def test_an_account_number_is_cut_to_its_last_four_digits(rendered: Rendered) -> None:
    lines, _ = lines_of(rendered, STUB)
    outcome = await FakeExtractor().extract("pay_stub", lines)
    stored = {p.name: p for p in prepare_fields("pay_stub", outcome, CFG)}["account_last4"]
    assert (stored.value, stored.normalized, stored.original) == ("6032", "6032", "6032")


async def test_the_august_statement_is_flagged_incomplete(rendered: Rendered) -> None:
    outcome, report = await check(rendered, AUGUST)

    # "Page 1 of 3" is printed, but only two pages were uploaded (FD 1.8, FSD T-09).
    [pages] = [f for f in report.findings if f.code == "DI-W701"]
    assert pages.message == (
        "Incomplete: this document says it has 3 pages, but 2 were uploaded; page 3 is missing."
    )
    assert pages.entity == "document"
    # Page 3's transactions are missing too, so the balances do not add up either.
    [balances] = [f for f in report.findings if f.code == "DI-CHK-05"]
    assert balances.message == (
        "Opening balance 5,845.26 plus transactions 881.00 is 6,726.26, "
        "not the closing balance 6,455.13."
    )
    assert review_codes(report) == {"DI-W701", "DI-CHK-05", "DI-CHK-06"}
    assert outcome.fields["closing_balance"].value == "6,455.13"


@pytest.mark.parametrize(
    "path",
    [
        SEPTEMBER,
        "angela_whitfield/bank_statement_2026-07.pdf",
        "angela_whitfield/bank_statement_2026-09.pdf",
        "angela_whitfield/pay_stub_2026-06-30.pdf",
        "angela_whitfield/pay_stub_2026-09-30.pdf",
    ],
)
async def test_the_documents_with_no_planted_defect_raise_no_flag(
    rendered: Rendered, path: str
) -> None:
    _, report = await check(rendered, path)
    assert review_codes(report) == set(), path
    assert set(report.certainty.values()) == {"high"}


async def test_a_type_with_no_reader_gives_no_fields_and_says_so(rendered: Rendered) -> None:
    lines, _ = lines_of(rendered, "daniel_reyes/credit_report_2026-10-12.pdf")
    outcome = await FakeExtractor().extract("credit_report", lines)
    assert outcome.fields == {} and outcome.signals == []
    _, report = await check(rendered, "daniel_reyes/credit_report_2026-10-12.pdf")
    assert [f.message for f in report.findings] == ["No fields were extracted from this document."]


async def test_a_required_field_the_reader_missed_gets_an_empty_row() -> None:
    lines = [DocLine(1, 1, "Acme Corp"), DocLine(1, 2, "EARNINGS STATEMENT")]
    outcome = await FakeExtractor().extract("pay_stub", lines)
    prepared = {p.name: p for p in prepare_fields("pay_stub", outcome, CFG)}
    net = prepared["net_pay_current"]
    assert (net.value, net.certainty, net.lines, net.required) == (None, "low", [], True)
    assert "pay_date" not in prepared  # optional fields are not invented


# --- the type decision (FSD 4.4) -------------------------------------------------------------


def result(doc_type: str, certainty: str) -> Classification:
    return Classification(doc_type, certainty, ["p1-L1"], [], "fake", "rule-based-v1")


@pytest.mark.parametrize(
    ("declared", "doc_type", "certainty", "applied", "source", "choose", "flag"),
    [
        (None, "pay_stub", "high", "pay_stub", "ai", False, None),  # applied only when certain
        (None, "pay_stub", "medium", None, "ai", True, "DI-W501"),
        (None, "pay_stub", "low", None, "ai", True, "DI-W501"),
        (None, "unrecognized", "high", None, "ai", True, "DI-W501"),  # stays "type needed"
        ("pay_stub", "pay_stub", "high", "pay_stub", "user", False, None),
        ("pay_stub", "pay_stub", "low", "pay_stub", "user", False, None),
        # A bank statement chosen as a tax return: a certain model disagrees, so hold and ask.
        ("tax_return_1040", "bank_statement", "high", None, "user", True, "DI-W502"),
        # A less certain disagreement proceeds with the person's choice and flags it.
        (
            "tax_return_1040",
            "bank_statement",
            "medium",
            "tax_return_1040",
            "user",
            False,
            "DI-W502",
        ),
        ("tax_return_1040", "unrecognized", "high", "tax_return_1040", "user", False, None),
    ],
)
def test_decide_type(
    declared: str | None,
    doc_type: str,
    certainty: str,
    applied: str | None,
    source: str,
    choose: bool,
    flag: str | None,
) -> None:
    decision = decide_type(declared, result(doc_type, certainty))
    assert (decision.doc_type, decision.source, decision.needs_choice, decision.flag) == (
        applied,
        source,
        choose,
        flag,
    )
    assert (decision.predicted, decision.selected) == (doc_type, declared)


async def test_the_september_statement_declared_as_a_tax_return_holds_for_a_choice(
    rendered: Rendered,
) -> None:
    entry = rendered.entry(SEPTEMBER)
    assert entry["declared_type"] == "tax_return_1040"  # the manifest's planted mismatch
    lines, _ = lines_of(rendered, SEPTEMBER)
    decision = decide_type(entry["declared_type"], await FakeClassifier().classify(lines))
    assert (decision.doc_type, decision.needs_choice, decision.flag) == (None, True, "DI-W502")
    assert (decision.predicted, decision.selected) == ("bank_statement", "tax_return_1040")


# --- choosing the implementation: real when it exists, the fake otherwise --------------------


def test_fake_mode_always_uses_the_fake() -> None:
    assert isinstance(get_classifier("fake"), FakeClassifier)
    assert isinstance(get_extractor("fake"), FakeExtractor)


def test_auto_uses_the_real_classify_task_when_it_exists(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(classification, "llm_tasks", lambda: SimpleNamespace(classify=object()))
    assert isinstance(get_classifier("auto"), LlmClassifier)


def test_auto_falls_back_to_the_fake_only_when_the_task_is_absent(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setattr(classification, "llm_tasks", lambda: None)
    monkeypatch.setattr(extractor, "llm_tasks", lambda: None)
    with caplog.at_level(logging.WARNING):
        assert isinstance(get_classifier("auto"), FakeClassifier)
        assert isinstance(get_extractor("auto"), FakeExtractor)
    assert "rule-based fake reader" in caplog.text  # it says which it uses


def test_auto_uses_the_fake_extractor_while_only_classify_exists(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Today's state of Arindam's branch: classify is real, extract is not there yet.
    tasks = SimpleNamespace(classify=object())
    monkeypatch.setattr(classification, "llm_tasks", lambda: tasks)
    monkeypatch.setattr(extractor, "llm_tasks", lambda: tasks)
    assert isinstance(get_classifier("auto"), LlmClassifier)
    assert isinstance(get_extractor("auto"), FakeExtractor)


def test_auto_uses_the_real_extract_task_when_it_exists(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(extractor, "llm_tasks", lambda: SimpleNamespace(extract=object()))
    assert isinstance(get_extractor("auto"), LlmExtractor)
    assert isinstance(get_extractor("fake"), FakeExtractor)  # forcing the fake still works


async def test_the_real_extractor_is_a_loud_error_if_the_task_vanishes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(extractor, "llm_tasks", lambda: None)
    with pytest.raises(PipelineUnavailableError, match="not available"):
        await LlmExtractor().extract("pay_stub", [])


def test_a_task_module_that_is_broken_is_never_hidden_behind_the_fake(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def broken() -> None:
        raise ImportError("langchain_core is missing")

    monkeypatch.setattr(classification, "llm_tasks", broken)
    with pytest.raises(ImportError, match="langchain_core"):
        get_classifier("auto")

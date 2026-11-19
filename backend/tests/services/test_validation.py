"""The checks that run in code on an extracted document (FSD 4.3 and 4.4). No database, no model."""

from __future__ import annotations

from dataclasses import replace
from decimal import Decimal

import pytest

from app.services.document_config import get_document_fields, get_validation_config
from app.services.validation import (
    Finding,
    LineInput,
    PageInput,
    ValidationInput,
    ValidationReport,
    validate,
    value_in_lines,
)
from tests.services.builders import (
    BANK_LINES,
    STUB_LINES,
    bank_statement,
    make_field,
    pay_stub,
)

RULES = get_validation_config()
CFG = get_document_fields()


def run(inp: ValidationInput) -> ValidationReport:
    report = validate(inp, RULES, CFG)
    keys = [(f.entity, f.field, f.code) for f in report.findings]
    assert len(keys) == len(set(keys)), "one finding per entity and code (flags are unique)"
    return report


def codes(report: ValidationReport, *, review_only: bool = True) -> list[str]:
    return [f.code for f in report.findings if f.marks_review or not review_only]


def only(report: ValidationReport, code: str) -> Finding:
    [found] = [f for f in report.findings if f.code == code]
    return found


def stub_with(**changes: tuple[str, tuple[str, ...]]) -> ValidationInput:
    """The stub with some values changed, and their printed lines changed to match."""
    lines = dict(STUB_LINES)
    return pay_stub(changes, lines=lines)


# --- pay stub: the net pay arithmetic (Feature Design 1.8, FSD T-07) ------------------------


def test_daniels_printed_net_pay_fails_the_net_pay_check() -> None:
    report = run(pay_stub())  # net pay 2,083.61 is printed on p1-L31

    assert codes(report) == ["DI-CHK-02"]  # and nothing else: the other checks all pass
    flag = only(report, "DI-CHK-02")
    assert flag.message == "Gross 3,070.50 minus deductions 1,036.89 is 2,033.61, not 2,083.61."
    assert (flag.entity, flag.field, flag.severity) == ("field", "net_pay_current", "warning")
    assert flag.lines == ("p1-L17", "p1-L25", "p1-L31")  # gross, deductions and net, as evidence
    assert flag.working == {
        "formula": "gross - deductions",
        "gross": "3070.50",
        "deductions": "1036.89",
        "expected": "2033.61",
        "printed": "2083.61",
        "difference": "50.00",
        "tolerance": "0.01",
    }
    assert all(Decimal(flag.working[k]) for k in ("gross", "deductions", "expected", "printed"))


def test_the_value_is_in_its_cited_line_so_only_the_arithmetic_catches_it() -> None:
    report = run(pay_stub())
    assert report.found["net_pay_current"] is True  # "2,083.61" really is on p1-L31
    assert "DI-W601" not in codes(report)


def test_a_correct_stub_raises_no_flag_that_needs_review() -> None:
    inp = pay_stub(
        {"net_pay_current": ("2,033.61", ("p1-L31",))},
        lines={**STUB_LINES, "p1-L31": "Net Pay 2,033.61"},
    )
    report = run(inp)
    assert report.findings == ()
    assert set(report.certainty.values()) == {"high"}


@pytest.mark.parametrize(
    ("net", "fails"),
    [
        ("2,033.61", False),
        ("2,033.62", False),
        ("2,033.60", False),
        ("2,033.63", True),
        ("2,033.59", True),
    ],
)
def test_the_tolerance_comes_from_config_and_is_one_cent(net: str, fails: bool) -> None:
    assert RULES.arithmetic_tolerance == Decimal("0.01")
    inp = pay_stub(
        {"net_pay_current": (net, ("p1-L31",))}, lines={**STUB_LINES, "p1-L31": f"Net Pay {net}"}
    )
    assert ("DI-CHK-02" in codes(run(inp))) is fails


def test_the_tolerance_is_a_setting_not_a_constant() -> None:
    loose = RULES.model_copy(update={"arithmetic_tolerance": Decimal("100.00")})
    assert "DI-CHK-02" not in [f.code for f in validate(pay_stub(), loose, CFG).findings]


def test_earnings_that_do_not_add_up_to_gross_fail_check_01() -> None:
    lines = {**STUB_LINES, "p1-L15": "Overtime 1.5x 3.96 51.75 300.00 3,897.10"}
    report = run(pay_stub({"earnings_overtime_current": ("300.00", ("p1-L15",))}, lines=lines))
    flag = only(report, "DI-CHK-01")
    assert flag.message == "Earnings add up to 3,165.57, but gross pay is 3,070.50."
    assert (flag.field, flag.working["sum"]) == ("gross_pay_current", "3165.57")
    assert "p1-L14" in flag.lines and "p1-L17" in flag.lines


def test_a_pay_period_that_ends_before_it_starts_fails_check_03() -> None:
    lines = {**STUB_LINES, "p1-L9": "Pay period: 2026-09-28 to 2026-09-27"}
    report = run(pay_stub({"pay_period_start": ("2026-09-28", ("p1-L9",))}, lines=lines))
    flag = only(report, "DI-CHK-03")
    assert flag.message == "Pay period start 2026-09-28 is after its end 2026-09-27."
    assert flag.field == "pay_period_start"


def test_year_to_date_below_the_current_period_fails_check_04() -> None:
    lines = {**STUB_LINES, "p1-L29": "Gross pay, year to date 1,000.00"}
    report = run(pay_stub({"gross_pay_ytd": ("1,000.00", ("p1-L29",))}, lines=lines))
    flag = only(report, "DI-CHK-04")
    assert flag.message == "Year-to-date gross 1,000.00 is below the current period's 3,070.50."


# --- missing, unreadable and unfound values -------------------------------------------------


def test_a_check_with_a_missing_input_says_it_cannot_check() -> None:
    report = run(pay_stub(drop=("total_deductions_current",)))
    cannot = only(report, "DI-CHK-02")
    assert cannot.severity == "info" and not cannot.marks_review
    assert cannot.message == (
        "Cannot check that gross pay minus deductions is net pay: Total deductions not found."
    )
    assert cannot.entity == "document"


def test_a_required_field_without_a_value_is_flagged_and_stops_the_checks_that_need_it() -> None:
    report = run(pay_stub({"net_pay_current": (None, ())}))
    missing = only(report, "DI-W604")
    assert missing.message == "Net pay wasn't found in this document."
    assert (missing.entity, missing.field) == ("field", "net_pay_current")
    assert only(report, "DI-CHK-02").severity == "info"  # cannot check, not a silent pass
    assert report.certainty["net_pay_current"] == "low"


def test_an_optional_field_without_a_value_is_not_flagged() -> None:
    report = run(pay_stub({"pay_date": (None, ())}))
    assert "DI-W604" not in codes(report)


def test_a_rejected_value_counts_as_missing() -> None:
    inp = pay_stub()
    net = replace(inp.fields["net_pay_current"], review_status="rejected")
    report = run(replace(inp, fields={**inp.fields, "net_pay_current": net}))
    assert "DI-W604" in codes(report)  # required, and a person said it is wrong
    assert only(report, "DI-CHK-02").severity == "info"


def test_a_value_that_cannot_be_read_as_an_amount_is_flagged() -> None:
    report = run(pay_stub({"net_pay_current": ("about 2k", ("p1-L31",))}))
    flag = only(report, "DI-W605")
    assert flag.message == "Net pay could not be read as an amount."
    assert report.certainty["net_pay_current"] == "low"


def test_a_value_that_is_not_in_its_cited_line_is_flagged() -> None:
    report = run(pay_stub({"net_pay_current": ("2,033.61", ("p1-L31",))}))  # line says 2,083.61
    flag = only(report, "DI-W601")
    assert flag.message == "We couldn't find this value in the text it came from."
    assert flag.field == "net_pay_current" and report.found["net_pay_current"] is False
    assert report.certainty["net_pay_current"] == "low"


def test_a_cited_line_that_does_not_exist_is_flagged() -> None:
    report = run(pay_stub({"net_pay_current": ("2,083.61", ("p9-L99",))}))
    assert only(report, "DI-W601").field == "net_pay_current"


def test_a_value_with_no_evidence_at_all_is_flagged() -> None:
    report = run(pay_stub({"net_pay_current": ("2,083.61", ())}))
    assert only(report, "DI-W601").field == "net_pay_current"


def test_a_value_matches_only_as_a_whole_amount() -> None:
    lines = {**STUB_LINES, "p1-L31": "Net Pay 12,083.61"}
    report = run(pay_stub(lines=lines))  # 2,083.61 is not "in" 12,083.61
    assert "DI-W601" in codes(report)


# --- value in lines, by kind ----------------------------------------------------------------


@pytest.mark.parametrize(
    ("kind", "value", "texts", "expected"),
    [
        ("amount", "2083.61", ["Net Pay 2,083.61"], True),
        ("amount", "2083.61", ["Net Pay $2,083.61 total"], True),
        ("amount", "-1425.00", ["2026-08-01 RENT -1,425.00 4,420.26"], True),
        ("amount", "-12.50", ["Fee (12.50)"], True),
        ("amount", "2083.61", ["Net Pay 12,083.61"], False),
        ("amount", "2083.61", ["Net Pay 2,083.6"], False),
        ("amount", "2083.61", [], False),
        ("date", "2026-09-27", ["Pay period: 2026-09-14 to 2026-09-27"], True),
        ("date", "2026-09-27", ["through 09/27/2026"], True),
        ("date", "2026-09-27", ["Sep 27, 2026"], True),
        ("date", "2026-09-27", ["Pay date: 2026-10-02"], False),
        ("id_last4", "6032", ["Direct deposit: account ending 6032"], True),
        ("id_last4", "6032", ["Account 0000-1234-6032"], True),
        ("id_last4", "6032", ["Account ending 6033"], False),
        ("text", "Cedar Valley Manufacturing, Inc.", ["cedar  valley manufacturing, inc."], True),
        ("text", "Daniel Reyes", ["Employee: Daniel Reyes", "Employee ID: E-20417"], True),
        ("text", "Daniel Reyes", ["Employee: Maria Reyes"], False),
    ],
)
def test_value_in_lines(kind: str, value: str, texts: list[str], expected: bool) -> None:
    assert value_in_lines(kind, value, texts) is expected


# --- printed page counts (FD 1.8: the August statement) -------------------------------------


def test_page_x_of_y_against_the_pages_uploaded_flags_a_missing_page() -> None:
    lines = {**STUB_LINES, "p1-L34": "Page 1 of 3", "p2-L19": "Page 2 of 3"}
    report = run(
        pay_stub(lines=lines, pages=(PageInput(1, "Page 1 of 3"), PageInput(2, "Page 2 of 3")))
    )
    flag = only(report, "DI-W701")
    assert flag.message == (
        "Incomplete: this document says it has 3 pages, but 2 were uploaded; page 3 is missing."
    )
    assert (flag.entity, flag.field, flag.severity) == ("document", None, "warning")
    assert flag.lines == ("p1-L34", "p2-L19")  # the footers are the evidence
    assert flag.working["printed_total"] == 3 and flag.working["uploaded"] == 2


def test_several_missing_pages_are_named() -> None:
    pages = (PageInput(1, "Page 1 of 4"), PageInput(2, "Page 2 of 4"))
    report = run(pay_stub(pages=pages))
    assert "pages 3, 4 are missing" in only(report, "DI-W701").message


def test_a_page_count_that_matches_raises_nothing() -> None:
    assert "DI-W701" not in codes(run(pay_stub()))


def test_pages_with_no_printed_count_raise_nothing() -> None:
    assert "DI-W701" not in codes(run(pay_stub(pages=(PageInput(1), PageInput(2)))))


def test_signs_of_an_incomplete_document_are_flagged() -> None:
    inp = replace(pay_stub(), signals=("a table is cut off at the bottom of page 1",))
    flag = only(run(inp), "DI-W701")
    assert flag.message == (
        "This document may be incomplete: a table is cut off at the bottom of page 1."
    )


def test_a_signal_and_a_page_mismatch_become_one_flag() -> None:
    inp = replace(
        pay_stub(pages=(PageInput(1, "Page 1 of 3"), PageInput(2, "Page 2 of 3"))),
        signals=("a continued notice",),
    )
    flags = [f for f in run(inp).findings if f.code == "DI-W701"]
    assert len(flags) == 1
    assert "page 3 is missing" in flags[0].message and "a continued notice" in flags[0].message


# --- bank statement -------------------------------------------------------------------------


def test_a_correct_statement_raises_nothing_that_needs_review() -> None:
    report = run(bank_statement())
    assert report.findings == ()
    assert set(report.certainty.values()) == {"high"}


def test_balances_that_do_not_reconcile_fail_check_05() -> None:
    lines = {**BANK_LINES, "p1-L11": "Closing balance 960.00"}
    inp = bank_statement({"closing_balance": ("960.00", ("p1-L11",))})
    inp = replace(inp, lines={r: LineInput(r, t) for r, t in lines.items()})
    flag = only(run(inp), "DI-CHK-05")
    assert flag.message == (
        "Opening balance 1,000.00 plus transactions -50.00 is 950.00, "
        "not the closing balance 960.00."
    )
    assert flag.field == "closing_balance"
    assert flag.working["transaction_count"] == 2 and flag.working["difference"] == "10.00"


def test_a_printed_total_that_does_not_match_the_transactions_fails_check_06() -> None:
    lines = {**BANK_LINES, "p1-L9": "Total deposits and credits 75.00"}
    inp = replace(
        bank_statement({"total_deposits": ("75.00", ("p1-L9",))}),
        lines={r: LineInput(r, t) for r, t in lines.items()},
    )
    flag = only(run(inp), "DI-CHK-06")
    assert flag.message == (
        "The printed total deposits and credits 75.00 does not match 50.00 "
        "from the transactions listed."
    )
    assert flag.field == "total_deposits"


def test_a_running_balance_that_does_not_follow_fails_check_07() -> None:
    lines = {**BANK_LINES, "p1-L15": "2026-08-05 PAYROLL 50.00 960.00"}
    inp = replace(
        bank_statement({"txn_002_balance": ("960.00", ("p1-L15",))}),
        lines={r: LineInput(r, t) for r, t in lines.items()},
    )
    flag = only(run(inp), "DI-CHK-07")
    assert flag.message == (
        "The running balance after 2026-08-05 PAYROLL is 960.00, but 950.00 was expected."
    )
    assert flag.field == "txn_002_balance"


def test_only_the_first_broken_running_balance_is_reported() -> None:
    lines = {
        **BANK_LINES,
        "p1-L14": "2026-08-01 RENT -100.00 800.00",
        "p1-L15": "2026-08-05 PAYROLL 50.00 700.00",
    }
    inp = replace(
        bank_statement(
            {"txn_001_balance": ("800.00", ("p1-L14",)), "txn_002_balance": ("700.00", ("p1-L15",))}
        ),
        lines={r: LineInput(r, t) for r, t in lines.items()},
    )
    flagged = [f.field for f in run(inp).findings if f.code == "DI-CHK-07"]
    assert flagged == ["txn_001_balance"]


def test_a_transaction_outside_the_statement_period_fails_check_08() -> None:
    lines = {**BANK_LINES, "p1-L15": "2026-09-05 PAYROLL 50.00 950.00"}
    inp = replace(
        bank_statement({"txn_002_date": ("2026-09-05", ("p1-L15",))}),
        lines={r: LineInput(r, t) for r, t in lines.items()},
    )
    flag = only(run(inp), "DI-CHK-08")
    assert flag.message == (
        "Transaction dated 2026-09-05 is outside the statement period 2026-08-01 to 2026-08-31."
    )
    assert flag.field == "txn_002_date"


def test_a_statement_period_that_ends_before_it_starts_fails_check_08() -> None:
    lines = {**BANK_LINES, "p1-L6": "Statement period: 2026-08-31 to 2026-08-01"}
    inp = replace(
        bank_statement(
            {
                "statement_period_start": ("2026-08-31", ("p1-L6",)),
                "statement_period_end": ("2026-08-01", ("p1-L6",)),
            }
        ),
        lines={r: LineInput(r, t) for r, t in lines.items()},
    )
    flag = only(run(inp), "DI-CHK-08")
    assert flag.message == "Statement period start 2026-08-31 is after its end 2026-08-01."
    assert flag.field == "statement_period_start"


def test_a_statement_without_totals_cannot_check_them() -> None:
    report = run(bank_statement(drop=("total_deposits", "total_withdrawals")))
    cannot = only(report, "DI-CHK-06")
    assert cannot.severity == "info"
    assert (
        "Total deposits and credits" in cannot.message
        and "Total withdrawals and debits" in cannot.message
    )


def test_a_statement_without_transactions_cannot_check_the_balances() -> None:
    names = tuple(n for n in bank_statement().fields if n.startswith("txn_"))
    report = run(bank_statement(drop=names))
    assert "transactions not found" in only(report, "DI-CHK-05").message


# --- certainty (FSD 4.4) ---------------------------------------------------------------------


def _certainty(reader: str, *, confidence: float | None = None, found: bool = True) -> str:
    inp = pay_stub({"employee_name": ("Daniel Reyes", ("p1-L5",))})
    lines = dict(inp.lines)
    lines["p1-L5"] = LineInput(
        "p1-L5", "Employee: Daniel Reyes" if found else "Employee: Someone", confidence
    )
    field = make_field("pay_stub", "employee_name", "Daniel Reyes", ("p1-L5",), certainty=reader)
    inp = replace(inp, lines=lines, fields={**inp.fields, "employee_name": field})
    return run(inp).certainty["employee_name"]


@pytest.mark.parametrize(
    ("reader", "confidence", "found", "expected"),
    [
        ("high", None, True, "high"),  # a text-layer line has no OCR confidence and meets the bar
        ("high", 0.95, True, "high"),
        ("high", 0.80, True, "high"),  # exactly the threshold meets it
        ("high", 0.79, True, "low"),  # a cited line below the OCR threshold
        ("medium", 0.99, True, "medium"),
        ("low", 0.99, True, "low"),  # the reader itself said low
        ("high", None, False, "low"),  # the value is not in its lines
    ],
)
def test_certainty_follows_the_fsd_rules(
    reader: str, confidence: float | None, found: bool, expected: str
) -> None:
    assert _certainty(reader, confidence=confidence, found=found) == expected


def test_every_field_gets_a_certainty() -> None:
    inp = pay_stub()
    assert set(run(inp).certainty) == set(inp.fields)


# --- a person has looked at it ---------------------------------------------------------------


def _reviewed(
    name: str, status: str, value: str, lines: dict[str, str] | None = None
) -> ValidationInput:
    inp = pay_stub()
    changed = make_field("pay_stub", name, value, inp.fields[name].lines, review=status)
    result = replace(inp, fields={**inp.fields, name: changed})
    return replace(result, lines={r: LineInput(r, t) for r, t in (lines or STUB_LINES).items()})


def test_a_corrected_value_need_not_appear_in_the_cited_line() -> None:
    report = run(
        _reviewed("net_pay_current", "corrected", "2,033.61")
    )  # the line still says 2,083.61
    assert (
        report.findings == ()
    )  # not found-in-line (the person typed it), and the arithmetic now holds
    assert report.certainty["net_pay_current"] == "high"
    assert report.found["net_pay_current"] is True


def test_a_correction_that_is_still_wrong_still_fails_the_arithmetic() -> None:
    report = run(_reviewed("net_pay_current", "corrected", "2,000.00"))
    assert codes(report) == ["DI-CHK-02"]
    assert only(report, "DI-CHK-02").message.endswith("not 2,000.00.")


def test_a_confirmed_value_is_not_asked_to_be_found_again() -> None:
    lines = {**STUB_LINES, "p1-L5": "Employee: someone else"}
    report = run(_reviewed("employee_name", "confirmed", "Daniel Reyes", lines))
    assert "DI-W601" not in codes(report)
    assert report.certainty["employee_name"] == "high"


def test_a_corrected_value_that_cannot_be_read_is_still_flagged() -> None:
    report = run(_reviewed("net_pay_current", "corrected", "lots"))
    assert "DI-W605" in codes(report)


# --- a type no reader is configured for ------------------------------------------------------


def test_a_type_with_no_configured_fields_says_nothing_was_extracted() -> None:
    inp = ValidationInput("credit_report", {}, {}, (PageInput(1),))
    flag = only(run(inp), "DI-W604")
    assert flag.message == "No fields were extracted from this document."
    assert (flag.entity, flag.field) == ("document", None)


def test_a_configured_type_with_no_fields_extracted_is_not_that_flag() -> None:
    # A pay stub the reader returned nothing for: required fields are missing, not "no reader".
    inp = ValidationInput("pay_stub", {}, {}, (PageInput(1),))
    assert [f for f in run(inp).findings if f.code == "DI-W604"] == []

"""Completeness against a checklist (FSD section 7): Daniel Reyes's gaps and the rules behind them.

Daniel's pay stubs cover 14 of 30 days, his 2024 W-2 and return are absent, his August statement
says "Page 1 of 3" with two pages, and his credit report has not been read for a date. Overall:
incomplete.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta

import pytest

from app.services.analysis_config import get_analysis_config
from app.services.case_facts import DocFacts, FieldFact
from app.services.completeness import (
    CompletenessOutcome,
    ItemResult,
    Profile,
    add_months,
    evaluate,
    longest,
    merge_ranges,
    months_covered,
    name_tokens,
    outstanding_of,
    overall_of,
    owner_of,
    span_days,
)

CFG = get_analysis_config()
WAGE = CFG.checklists.checklists["pillar1-wage-earner@1"]
HARDSHIP = CFG.checklists.checklists["pillar2-hardship@1"]
DANIEL = Profile(["Daniel Reyes"], date(2026, 10, 12))
BASE_TIME = datetime(2026, 10, 12, tzinfo=UTC)


def d(text: str) -> date:
    return date.fromisoformat(text)


def doc(
    doc_type: str,
    *,
    borrower: str | None = "Daniel Reyes",
    start: str | None = None,
    end: str | None = None,
    fields: dict[str, str] | None = None,
    flags: tuple[str, ...] = (),
    status: str = "needs_review",
    minutes: int = 0,
) -> DocFacts:
    facts = {
        name: FieldFact(name, value, value, ("p1-L1",), "unreviewed", "high")
        for name, value in (fields or {}).items()
    }
    return DocFacts(
        uuid.uuid4(),
        f"{doc_type}.pdf",
        doc_type,
        status,
        borrower,
        d(start) if start else None,
        d(end) if end else None,
        BASE_TIME + timedelta(minutes=minutes),
        facts,
        frozenset(flags),
    )


def stub(start: str = "2026-09-14", end: str = "2026-09-27", **kw: object) -> DocFacts:
    return doc("pay_stub", start=start, end=end, **kw)  # type: ignore[arg-type]


def statement(start: str, end: str, account: str = "6032", **kw: object) -> DocFacts:
    return doc("bank_statement", start=start, end=end, fields={"account_last4": account}, **kw)  # type: ignore[arg-type]


def w2(year: str, **kw: object) -> DocFacts:
    return doc("w2", fields={"tax_year": year}, **kw)  # type: ignore[arg-type]


def form_1040(year: str, **kw: object) -> DocFacts:
    return doc("tax_return_1040", fields={"tax_year": year}, borrower="Daniel Reyes", **kw)  # type: ignore[arg-type]


def credit(report_date: str | None = None) -> DocFacts:
    return doc("credit_report", fields={"report_date": report_date} if report_date else None)


def daniels_case() -> list[DocFacts]:
    return [
        stub(),
        statement("2026-08-01", "2026-08-31", flags=("DI-W701",)),  # "Page 1 of 3", two pages
        statement("2026-09-01", "2026-09-30"),
        w2("2025"),
        form_1040("2025"),
        credit(),
    ]


def run(
    docs: list[DocFacts], checklist: object = WAGE, profile: Profile = DANIEL
) -> CompletenessOutcome:
    return evaluate(checklist, CFG.checklists, profile, docs)  # type: ignore[arg-type]


def item(outcome: CompletenessOutcome, item_id: str) -> ItemResult:
    return next(i for i in outcome.items if i.item_id == item_id)


# --- Daniel Reyes ---------------------------------------------------------------------------


def test_daniels_gaps() -> None:
    outcome = run(daniels_case())

    stubs = item(outcome, "pay_stubs_30_days")
    assert (stubs.status, stubs.reason) == ("partial", "14 of 30 days of pay stubs found")
    w2s = item(outcome, "w2_two_years")
    assert (w2s.status, w2s.reason) == ("partial", "W-2s found for 2025; missing 2024")
    returns = item(outcome, "tax_returns_two_years")
    assert (returns.status, returns.reason) == (
        "partial",
        "Tax returns found for 2025; missing 2024",
    )
    banks = item(outcome, "bank_statements_2_months")
    assert banks.status == "partial"  # two months are there, but one statement is incomplete
    assert banks.reason == (
        "Bank statements: a document is incomplete (a page is missing or a table is cut off)"
    )
    assert len(banks.document_ids) == 2
    report = item(outcome, "credit_report_120_days")
    assert (report.status, report.reason) == (
        "needs_review",
        "Credit report: the date of the document was not read",
    )
    assert outcome.overall == "incomplete"  # never a decision: a list of what is outstanding


def test_the_outstanding_list_names_every_open_item_in_plain_text() -> None:
    outcome = run(daniels_case())
    assert outcome.outstanding == [
        "Pay stubs covering 30 days: 14 of 30 days of pay stubs found",
        "W-2s for the last two tax years: W-2s found for 2025; missing 2024",
        "Tax returns for the last two tax years: Tax returns found for 2025; missing 2024",
        "Bank statements covering two months: Bank statements: a document is incomplete "
        "(a page is missing or a table is cut off)",
        "Credit report within 120 days: Credit report: the date of the document was not read",
    ]


def test_with_everything_in_the_case_the_checklist_is_complete() -> None:
    docs = [
        stub(),
        stub("2026-09-28", "2026-10-11", minutes=1),
        stub("2026-08-31", "2026-09-13", minutes=2),
        statement("2026-08-01", "2026-08-31"),
        statement("2026-09-01", "2026-09-30"),
        w2("2025"),
        w2("2024"),
        form_1040("2025"),
        form_1040("2024"),
        credit("2026-10-12"),
    ]
    outcome = run(docs)
    assert [i.status for i in outcome.items] == ["satisfied"] * 5
    assert outcome.overall == "complete" and outcome.outstanding == []
    assert item(outcome, "pay_stubs_30_days").reason == "42 of 30 days of pay stubs found"


def test_an_item_can_name_the_documents_it_used() -> None:
    docs = daniels_case()
    stubs = item(run(docs), "pay_stubs_30_days")
    assert stubs.document_ids == [str(docs[0].id)]


# --- coverage in days -----------------------------------------------------------------------


def test_adjacent_ranges_are_one_continuous_span() -> None:
    # The FSD's own example: 2026-09-14 to 09-27 and 09-28 to 10-11 are one 28-day span.
    spans = merge_ranges([(d("2026-09-14"), d("2026-09-27")), (d("2026-09-28"), d("2026-10-11"))])
    assert spans == [(d("2026-09-14"), d("2026-10-11"))]
    assert span_days(spans[0]) == 28
    stubs = item(run([stub(), stub("2026-09-28", "2026-10-11", minutes=1)]), "pay_stubs_30_days")
    assert stubs.reason == "28 of 30 days of pay stubs found" and stubs.status == "partial"


def test_a_gap_between_stubs_means_only_the_longest_span_counts() -> None:
    far = stub("2026-08-03", "2026-08-16", minutes=1)  # two weeks, a month before the other
    found = item(run([stub(), far]), "pay_stubs_30_days")
    assert found.reason == "14 of 30 days of pay stubs found"


def test_overlapping_and_duplicate_ranges_are_not_counted_twice() -> None:
    spans = merge_ranges(
        [
            (d("2026-09-01"), d("2026-09-20")),
            (d("2026-09-10"), d("2026-09-30")),
            (d("2026-09-10"), d("2026-09-30")),
        ]
    )
    assert spans == [(d("2026-09-01"), d("2026-09-30"))] and span_days(spans[0]) == 30
    assert item(run([stub("2026-09-01", "2026-09-30")]), "pay_stubs_30_days").status == "satisfied"


def test_the_longest_span() -> None:
    spans = [(d("2026-01-01"), d("2026-01-10")), (d("2026-03-01"), d("2026-03-31"))]
    assert longest(spans) == (d("2026-03-01"), d("2026-03-31"))
    assert longest([]) is None


# --- coverage in months ---------------------------------------------------------------------


@pytest.mark.parametrize(
    ("start", "end", "months"),
    [
        ("2026-08-01", "2026-09-30", 2),  # start + 2 months - 1 day is 2026-09-30
        ("2026-08-01", "2026-09-29", 1),
        ("2026-08-01", "2026-08-31", 1),
        ("2026-08-01", "2026-08-30", 0),
        ("2024-01-31", "2024-02-29", 1),  # 31 January + 1 month is 29 February (leap year)
        ("2026-01-31", "2026-02-26", 0),
        ("2026-01-31", "2026-02-27", 1),  # 31 Jan + 1 month is 28 Feb; minus a day is 27 Feb
        ("2026-01-31", "2026-02-28", 1),
    ],
)
def test_n_months_of_coverage_means_the_end_is_on_or_after_start_plus_n_months_minus_a_day(
    start: str, end: str, months: int
) -> None:
    assert months_covered((d(start), d(end))) == months


@pytest.mark.parametrize(
    ("start", "months", "expected"),
    [
        ("2026-01-31", 1, "2026-02-28"),
        ("2024-01-31", 1, "2024-02-29"),
        ("2026-08-01", 2, "2026-10-01"),
        ("2026-12-15", 1, "2027-01-15"),
        ("2026-03-31", 12, "2027-03-31"),
    ],
)
def test_adding_months_keeps_the_day_where_the_month_has_it(
    start: str, months: int, expected: str
) -> None:
    assert add_months(d(start), months) == d(expected)


def test_two_statements_two_months_apart_cover_only_one_month_each() -> None:
    # Angela's case: July and September, no August.
    banks = item(
        run([statement("2026-07-01", "2026-07-31"), statement("2026-09-01", "2026-09-30")]),
        "bank_statements_2_months",
    )
    assert banks.status == "partial"
    assert banks.reason == "1 of 2 months of bank statements found for the account ending 6032"


def test_each_account_is_checked_on_its_own() -> None:
    docs = [
        statement("2026-08-01", "2026-09-30", "6032"),
        statement("2026-09-01", "2026-09-30", "7788"),
    ]
    banks = item(run(docs), "bank_statements_2_months")
    assert banks.status == "partial"
    assert banks.reason == (
        "2 of 2 months of bank statements found for the account ending 6032; "
        "1 of 2 months of bank statements found for the account ending 7788"
    )


def test_a_statement_whose_account_was_not_read_needs_review() -> None:
    odd = doc("bank_statement", start="2026-08-01", end="2026-09-30")
    banks = item(run([odd]), "bank_statements_2_months")
    assert banks.status == "needs_review"
    assert banks.reason == "Bank statements: the account of a document was not read"


# --- tax years ------------------------------------------------------------------------------


def test_the_required_tax_years_come_from_the_reference_year() -> None:
    assert item(run([w2("2025"), w2("2024")]), "w2_two_years").status == "satisfied"
    late = Profile(["Daniel Reyes"], date(2027, 2, 1))  # now 2026 and 2025 are the years needed
    found = item(run([w2("2025"), w2("2024")], profile=late), "w2_two_years")
    assert (found.status, found.reason) == ("partial", "W-2s found for 2025; missing 2026")


def test_only_the_other_years_documents_means_every_year_is_missing_but_the_item_exists() -> None:
    found = item(run([w2("2019")]), "w2_two_years")
    assert (found.status, found.reason) == ("partial", "W-2s found for none; missing 2024, 2025")


def test_a_tax_year_that_was_not_read_needs_review() -> None:
    unread = doc("w2")
    found = item(run([unread]), "w2_two_years")
    assert (found.status, found.reason) == (
        "needs_review",
        "W-2s: the tax year of a document was not read",
    )


def test_a_tax_year_after_the_reference_year_needs_review() -> None:
    found = item(run([w2("2027")]), "w2_two_years")
    assert found.status == "needs_review"
    assert found.reason == "W-2s: a document is for a tax year after the reference year"


# --- recency --------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("report_date", "status"),
    [
        ("2026-10-12", "satisfied"),  # the reference date itself
        ("2026-06-14", "satisfied"),  # 120 days before
        ("2026-06-13", "partial"),  # 121 days
        ("2026-10-13", "needs_review"),  # dated after the reference date
    ],
)
def test_a_credit_report_must_be_within_120_days_of_the_reference_date(
    report_date: str, status: str
) -> None:
    assert item(run([credit(report_date)]), "credit_report_120_days").status == status


def test_a_stale_report_says_how_stale() -> None:
    found = item(run([credit("2026-06-13")]), "credit_report_120_days")
    assert found.reason == (
        "Credit report dated 121 days before the reference date; at most 120 days is allowed"
    )


# --- who a document belongs to --------------------------------------------------------------


@pytest.mark.parametrize(
    ("doc_name", "expected"),
    [
        ("Daniel Reyes", "matched"),
        ("REYES, DANIEL A.", "matched"),
        ("Daniel Reyes and Maria Reyes", "matched"),  # a joint return
        ("daniel   reyes", "matched"),
        ("Maria Lopez", "other"),
        ("Daniel Okafor", "other"),
        (None, "unknown"),
        ("", "unknown"),
        ("A.", "unknown"),  # an initial is no name
    ],
)
def test_a_document_belongs_to_a_borrower_when_every_word_of_the_name_is_on_it(
    doc_name: str | None, expected: str
) -> None:
    assert owner_of(stub(borrower=doc_name), ["Daniel Reyes"]) == expected


def test_initials_are_ignored_on_both_sides() -> None:
    assert owner_of(stub(borrower="Daniel Reyes"), ["Daniel A. Reyes"]) == "matched"
    assert name_tokens("Daniel A. Reyes") == {"daniel", "reyes"}


def test_a_second_borrower_on_the_profile_matches_too() -> None:
    profile = Profile(["Daniel Reyes", "Maria Reyes"], date(2026, 10, 12))
    found = item(run([stub(borrower="Maria Reyes")], profile=profile), "pay_stubs_30_days")
    assert found.status == "partial"  # her stub counts, and it covers only 14 days


def test_documents_of_someone_else_do_not_count() -> None:
    found = item(run([stub(borrower="Maria Lopez")]), "pay_stubs_30_days")
    assert (found.status, found.reason) == ("missing", "No pay stubs found for Daniel Reyes")
    assert found.document_ids == []


def test_a_document_with_no_readable_owner_needs_review_not_a_guess() -> None:
    found = item(run([stub(borrower=None)]), "pay_stubs_30_days")
    assert found.status == "needs_review"
    assert found.reason == "Pay stubs: a document's owner could not be read"


# --- the first condition that holds wins ----------------------------------------------------


def test_missing_is_reported_when_there_is_nothing_of_the_type() -> None:
    outcome = run([])
    assert [i.status for i in outcome.items] == ["missing"] * 5
    assert item(outcome, "credit_report_120_days").reason == (
        "No credit report found for Daniel Reyes"
    )
    assert outcome.overall == "incomplete"


def test_a_failed_document_or_one_waiting_for_its_type_is_not_a_document() -> None:
    docs = [stub(status="failed"), stub(status="type_needed")]
    assert item(run(docs), "pay_stubs_30_days").status == "missing"


def test_a_future_dated_stub_needs_review_even_when_coverage_is_short() -> None:
    found = item(run([stub("2026-10-05", "2026-10-18")]), "pay_stubs_30_days")
    assert found.status == "needs_review"
    assert found.reason == "Pay stubs: a document is dated after the reference date"


def test_a_stub_whose_period_was_not_read_needs_review() -> None:
    found = item(run([doc("pay_stub")]), "pay_stubs_30_days")
    assert found.status == "needs_review"
    assert found.reason == "Pay stubs: the period of a document was not read"


def test_an_incomplete_document_is_added_to_a_partial_reason() -> None:
    found = item(run([stub(flags=("DI-W701",))]), "pay_stubs_30_days")
    assert found.status == "partial"
    assert found.reason == (
        "14 of 30 days of pay stubs found; pay stubs: a document is incomplete "
        "(a page is missing or a table is cut off)"
    )


def test_other_open_flags_do_not_make_a_document_incomplete() -> None:
    found = item(
        run([stub("2026-09-01", "2026-09-30", flags=("DI-W206", "DI-W501"))]), "pay_stubs_30_days"
    )
    assert found.status == "satisfied"


# --- the loss mitigation checklist ----------------------------------------------------------


def hardship_case(signed: bool = True) -> list[DocFacts]:
    return [
        doc(
            "mortgage_assistance_application",
            borrower="Angela Whitfield",
            fields={"signed_date": "2026-10-01"} if signed else {},
        ),
        doc("hardship_letter", borrower="Angela Whitfield"),
        stub("2026-09-01", "2026-09-30", borrower="Angela Whitfield"),
        statement("2026-08-01", "2026-09-30"),
    ]


ANGELA = Profile(["Angela Whitfield"], date(2026, 10, 12))


def test_the_hardship_checklist_has_its_four_items_and_is_complete_with_all_of_them() -> None:
    docs = hardship_case()
    docs[3] = doc(
        "bank_statement",
        borrower="Angela Whitfield",
        start="2026-08-01",
        end="2026-09-30",
        fields={"account_last4": "1234"},
    )
    outcome = run(docs, HARDSHIP, ANGELA)
    assert [i.item_id for i in outcome.items] == [
        "signed_application",
        "hardship_letter",
        "pay_stubs_30_days",
        "bank_statements_2_months",
    ]
    assert outcome.overall == "complete"


def test_an_application_with_no_signature_date_needs_review() -> None:
    outcome = run(hardship_case(signed=False), HARDSHIP, ANGELA)
    found = item(outcome, "signed_application")
    assert found.status == "needs_review"
    assert found.reason == "Mortgage assistance application: no signature date was read"


def test_a_missing_hardship_letter_is_missing() -> None:
    docs = [d for d in hardship_case() if d.doc_type != "hardship_letter"]
    found = item(run(docs, HARDSHIP, ANGELA), "hardship_letter")
    assert (found.status, found.reason) == (
        "missing",
        "No hardship letter found for Angela Whitfield",
    )


# --- the overall status and overrides -------------------------------------------------------


def _item(status: str, override: bool = False) -> ItemResult:
    return ItemResult(
        "x",
        "An item",
        status,
        "why",
        [],
        {"reason": "ok", "by": "u", "at": "t"} if override else None,  # type: ignore[arg-type]
    )


@pytest.mark.parametrize(
    ("statuses", "overall"),
    [
        (["satisfied", "satisfied"], "complete"),
        (["satisfied", "needs_review"], "needs_review"),
        (["satisfied", "partial"], "incomplete"),
        (["missing", "satisfied"], "incomplete"),
        (["needs_review", "partial"], "incomplete"),  # incomplete outranks needs review
        (["needs_review", "missing"], "incomplete"),
        ([], "complete"),
    ],
)
def test_the_overall_status(statuses: list[str], overall: str) -> None:
    assert overall_of([_item(s) for s in statuses]) == overall


def test_an_override_counts_as_satisfied_without_replacing_the_computed_status() -> None:
    items = [_item("partial", override=True), _item("satisfied")]
    assert overall_of(items) == "complete"
    assert items[0].status == "partial"  # what code computed is kept
    assert items[0].effective == "overridden" and items[1].effective == "satisfied"
    assert outstanding_of(items) == []


def test_an_overridden_item_is_not_outstanding_but_the_others_are() -> None:
    items = [_item("partial", override=True), _item("missing")]
    assert overall_of(items) == "incomplete"
    assert outstanding_of(items) == ["An item: why"]


def test_an_item_survives_a_round_trip_through_json() -> None:
    original = ItemResult("pay_stubs_30_days", "Pay stubs", "partial", "14 of 30", ["a", "b"], None)
    assert ItemResult.from_json(original.as_json()) == original
    with_override = ItemResult("i", "L", "missing", "r", [], {"reason": "ok", "by": "u", "at": "t"})
    assert ItemResult.from_json(with_override.as_json()).effective == "overridden"


def test_the_same_documents_always_give_the_same_result() -> None:
    docs = daniels_case()
    first, second = run(docs), run(docs)
    assert [i.as_json() for i in first.items] == [i.as_json() for i in second.items]
    assert first.overall == second.overall and first.outstanding == second.outstanding

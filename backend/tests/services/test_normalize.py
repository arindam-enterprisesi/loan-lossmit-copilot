"""Standard forms for amounts, dates and identifiers (plain code, no model)."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from app.services.normalize import (
    display_amount,
    display_value,
    last_four,
    normalize,
    parse_amount,
    parse_date,
    stored_text,
)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("2,083.61", "2083.61"),
        ("$2,083.61", "2083.61"),
        ("  3,070.50 ", "3070.50"),
        ("-1,425.00", "-1425.00"),
        ("(12.50)", "-12.50"),
        ("\N{MINUS SIGN}12.5", "-12.50"),
        ("5", "5.00"),
        ("0.00", "0.00"),
    ],
)
def test_amounts_become_exact_decimals(text: str, expected: str) -> None:
    amount = parse_amount(text)
    assert amount == Decimal(expected) and isinstance(amount, Decimal)
    assert normalize("amount", text) == expected


@pytest.mark.parametrize("text", ["", "abc", "12.345", "1.2.3", "12-34", "$", "--5", "1,23,4,5.0x"])
def test_an_unreadable_amount_is_not_normalised_never_rounded(text: str) -> None:
    assert parse_amount(text) is None
    assert normalize("amount", text) is None


def test_more_than_two_decimals_is_never_rounded_away() -> None:
    assert parse_amount("2033.615") is None


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("2026-09-27", date(2026, 9, 27)),
        ("09/27/2026", date(2026, 9, 27)),
        ("9/7/26", date(2026, 9, 7)),
        ("Sep 27, 2026", date(2026, 9, 27)),
        ("September 27, 2026", date(2026, 9, 27)),
        ("27 Sep 2026", date(2026, 9, 27)),
    ],
)
def test_dates_become_iso(text: str, expected: date) -> None:
    assert parse_date(text) == expected
    assert normalize("date", text) == expected.isoformat()


@pytest.mark.parametrize("text", ["", "2026-13-01", "13/45/2026", "tomorrow", "2026/09/27"])
def test_an_unreadable_date_is_not_normalised(text: str) -> None:
    assert normalize("date", text) is None


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("123-45-6789", "6789"),
        ("XXX-XX-6789", "6789"),
        ("Account ending 6032", "6032"),
        ("000123456032", "6032"),
        ("12 3", None),
        ("no digits", None),
        (None, None),
    ],
)
def test_identifiers_are_cut_to_their_last_four_digits(
    text: str | None, expected: str | None
) -> None:
    assert last_four(text) == expected
    assert stored_text("id_last4", text) == expected


def test_a_full_identifier_is_never_stored() -> None:
    stored = stored_text("id_last4", "SSN 123-45-6789")
    assert stored == "6789" and "123" not in stored
    assert normalize("id_last4", "SSN 123-45-6789") == "6789"


def test_text_is_trimmed_and_spacing_collapsed() -> None:
    squashed = normalize("text", "  Cedar   Valley\nManufacturing, Inc. ")
    assert squashed == "Cedar Valley Manufacturing, Inc."
    assert stored_text("text", "  ") is None and normalize("text", None) is None


def test_display_helpers() -> None:
    assert display_amount(Decimal("3070.5")) == "3,070.50"
    assert display_amount(Decimal("-1425")) == "-1,425.00"
    assert display_value("amount", "2033.61") == "2,033.61"
    assert display_value("id_last4", "6032") == "ending 6032"
    assert display_value("date", "2026-09-27") == "2026-09-27"
    assert display_value("amount", None) == "not found"

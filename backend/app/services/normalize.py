"""Standard forms for extracted values: amounts, dates, and last-four identifiers.

Everything here is plain code (CLAUDE.md rule 1): a model reads text, and this module turns it into
an exact ``Decimal``, an ISO date, or the last four digits of a number. Nothing is rounded away: an
amount with more than two decimals is not normalisable, so a person looks at it.
"""

from __future__ import annotations

import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

CENT = Decimal("0.01")
_AMOUNT = re.compile(r"^-?\d+(\.\d{1,2})?$")
_NUMBER = re.compile(r"^\d+(\.\d{1,4})?$")
_DATE_FORMATS = (
    "%Y-%m-%d",
    "%m/%d/%Y",
    "%m/%d/%y",
    "%b %d, %Y",
    "%B %d, %Y",
    "%d %b %Y",
    "%d %B %Y",
)


def parse_amount(text: str | None) -> Decimal | None:
    """``"$2,083.61"`` -> ``Decimal("2083.61")``; ``"(12.50)"`` and ``"-12.50"`` are negative."""
    if text is None:
        return None
    cleaned = text.strip().replace("\N{MINUS SIGN}", "-").replace("$", "").replace(",", "")
    cleaned = cleaned.replace(" ", "")
    if cleaned.startswith("(") and cleaned.endswith(")"):
        cleaned = "-" + cleaned[1:-1]
    if not _AMOUNT.match(cleaned):
        return None
    try:
        return Decimal(cleaned).quantize(CENT)
    except InvalidOperation:
        return None


def clean_number(text: str | None) -> str | None:
    """``"1,040.50"`` -> ``"1040.50"``: an unsigned quantity (hours, a rate), up to four decimals.

    The digits are kept exactly as printed, so ``"34.50"`` stays ``"34.50"``.
    """
    if text is None:
        return None
    cleaned = text.strip().replace(",", "").replace(" ", "")
    return cleaned if _NUMBER.match(cleaned) else None


def parse_number(text: str | None) -> Decimal | None:
    cleaned = clean_number(text)
    return None if cleaned is None else Decimal(cleaned)


def parse_date(text: str | None) -> date | None:
    if text is None:
        return None
    cleaned = " ".join(text.replace(".", "").split())
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(cleaned, fmt).date()
        except ValueError:
            continue
    return None


def last_four(text: str | None) -> str | None:
    """The last four digits of an SSN or account number; None if there are fewer than four."""
    digits = re.sub(r"\D", "", text or "")
    return digits[-4:] if len(digits) >= 4 else None


def normalize(kind: str, text: str | None) -> str | None:
    """The standard form of ``text`` for a field of this ``kind``; None if it cannot be read."""
    if text is None or not text.strip():
        return None
    if kind == "amount":
        amount = parse_amount(text)
        return None if amount is None else f"{amount:.2f}"
    if kind == "date":
        found = parse_date(text)
        return None if found is None else found.isoformat()
    if kind == "id_last4":
        return last_four(text)
    if kind == "number":
        return clean_number(text)
    return " ".join(text.split())


def stored_text(kind: str, text: str | None) -> str | None:
    """What may be written to the database for a value read from a document.

    Identifiers are cut to their last four digits here, before anything is stored, so a full SSN or
    account number never reaches ``fields``. A value that is not a valid identifier is dropped.
    """
    if text is None or not text.strip():
        return None
    if kind == "id_last4":
        return last_four(text)
    return " ".join(text.split())


def display_amount(value: Decimal) -> str:
    """``Decimal("3070.5")`` -> ``"3,070.50"`` (how amounts are shown in messages)."""
    return f"{value:,.2f}"


def display_value(kind: str, normalized: str | None) -> str:
    """A normalised value as shown in a message or summary."""
    if normalized is None:
        return "not found"
    if kind == "amount":
        amount = parse_amount(normalized)
        return display_amount(amount) if amount is not None else normalized
    if kind == "id_last4":
        return f"ending {normalized}"
    return normalized

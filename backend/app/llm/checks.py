"""Checks run in code on model output (Feature Design 2.5 and 7.5).

    verify_quotes()    every quote is an exact piece of the lines it cites
    check_figures()    every number in model-written text appears in the inputs
    decision_words()   no decision wording (CLAUDE.md rule 3)

None of these calls a model. Each returns what failed, and the caller attaches the
flag to the item, so a person sees it before relying on it.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Iterator, Sequence
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation

from pydantic import BaseModel

from app.llm.tasks import DocumentLine
from app.prompts.schemas.hardship import Quoted

UNVERIFIED_QUOTE = "unverified_quote"
QUOTE_TOO_LONG = "quote_too_long"
UNVERIFIED_FIGURE = "unverified figure"
DECISION_WORDING = "decision_wording"

# Typographic quotes and dashes a model may straighten (or curl) when copying.
_TYPOGRAPHY = str.maketrans(
    {"\u2018": "'", "\u2019": "'", "\u201c": '"', "\u201d": '"', "\u2013": "-", "\u2014": "-"}
)


def normalise(text: str) -> str:
    """Whitespace collapsed and typographic quotes straightened; case is kept."""
    return " ".join(text.translate(_TYPOGRAPHY).split())


# --- quotes ----------------------------------------------------------------------------------


@dataclass(frozen=True)
class QuoteCheck:
    path: str  # e.g. "primary_reason", "timeline[1]"
    quote: str | None
    lines: list[str]
    flags: list[str] = field(default_factory=list)

    @property
    def verified(self) -> bool:
        return not self.flags


def iter_quoted(model: BaseModel, prefix: str = "") -> Iterator[tuple[str, Quoted]]:
    """Every quoted item in a profile, with its path."""
    for name in type(model).model_fields:
        value = getattr(model, name)
        items = value if isinstance(value, list) else [value]
        for index, item in enumerate(items):
            path = f"{prefix}{name}[{index}]" if isinstance(value, list) else f"{prefix}{name}"
            if isinstance(item, Quoted):
                yield path, item
            if isinstance(item, BaseModel):
                yield from iter_quoted(item, f"{path}.")


def _line_order(line_id: str) -> tuple[int, int]:
    match = re.fullmatch(r"p(\d+)-L(\d+)", line_id)
    return (int(match[1]), int(match[2])) if match else (0, 0)


def verify_quotes(
    profile: BaseModel,
    lines: Sequence[DocumentLine],
    *,
    max_quote_chars: int | None = None,
) -> list[QuoteCheck]:
    """Check each quote is an exact substring of its cited lines, read in document order.

    Whitespace is normalised (a quote may run across a line break) and typographic
    quotes are straightened; nothing else is forgiven. A quote fails with
    ``unverified_quote`` if it is not found, cites no lines or cites a line that does
    not exist. An item with no quote and no lines ("not stated") passes.
    """
    text_by_id = {ln.line_id: ln.text for ln in lines}
    checks = []
    for path, item in iter_quoted(profile):
        flags: list[str] = []
        if item.quote is None:
            if item.lines:
                flags.append(UNVERIFIED_QUOTE)
        else:
            known = [lid for lid in item.lines if lid in text_by_id]
            cited = " ".join(text_by_id[lid] for lid in sorted(known, key=_line_order))
            needle = normalise(item.quote)
            if (
                not needle
                or not item.lines
                or len(known) != len(item.lines)
                or needle not in normalise(cited)
            ):
                flags.append(UNVERIFIED_QUOTE)
            if max_quote_chars is not None and len(item.quote) > max_quote_chars:
                flags.append(QUOTE_TOO_LONG)
        checks.append(QuoteCheck(path, item.quote, list(item.lines), flags))
    return checks


# --- figures ---------------------------------------------------------------------------------

# A number standing on its own: 4,457.92 / 5.49 / 2025 / 12. Not the digits inside
# "p1-L31" or "E-20417x", which are joined to letters.
_NUMBER = re.compile(r"(?<![\w.])(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?(?![\w])")


def _as_decimal(token: str) -> Decimal | None:
    try:
        return Decimal(token.replace(",", ""))
    except InvalidOperation:
        return None


def numbers_in(*texts: str) -> set[Decimal]:
    """Every number in the texts, as Decimal (so 4457.92 and 4,457.920 are the same)."""
    found = set()
    for text in texts:
        for token in _NUMBER.findall(text):
            value = _as_decimal(token)
            if value is not None:
                found.add(value)
    return found


def check_figures(text: str, allowed_numbers: Iterable[Decimal | str]) -> list[str]:
    """The numbers in ``text`` that are not among ``allowed_numbers``, as written.

    The model may only repeat figures it was given; any other number (a rounded,
    recomputed or invented one) is returned so the caller marks it "unverified figure".
    """
    allowed = {v if isinstance(v, Decimal) else _as_decimal(str(v)) for v in allowed_numbers} - {
        None
    }
    unverified = []
    for token in _NUMBER.findall(text):
        if _as_decimal(token) not in allowed:
            unverified.append(token)
    return list(dict.fromkeys(unverified))


# --- decision wording ------------------------------------------------------------------------

_DECISION = re.compile(
    r"\b(approv\w*|den(?:y|ies|ied|ial)|offer\w*|eligib\w*|qualif(?:y|ies|ied))\b",
    re.IGNORECASE,
)


def decision_words(text: str) -> list[str]:
    """Decision words found in model-written text (CLAUDE.md rule 3)."""
    return list(dict.fromkeys(m.lower() for m in _DECISION.findall(text)))

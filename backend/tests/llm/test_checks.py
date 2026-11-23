"""Code checks on model output: quotes, figures and decision wording."""

from decimal import Decimal

from app.llm.checks import (
    QUOTE_TOO_LONG,
    UNVERIFIED_QUOTE,
    check_figures,
    decision_words,
    numbers_in,
    verify_quotes,
)
from app.llm.samples import load_lines
from app.prompts.schemas.hardship import HardshipProfile

LETTER = load_lines("angela_hardship_letter")


def item(quote: str | None, *lines: str, **extra: object) -> dict[str, object]:
    return {"quote": quote, "lines": list(lines), **extra}


def profile(**overrides: object) -> HardshipProfile:
    body: dict[str, object] = {
        "primary_reason": item(
            "cut my hours from 40 to 30 a week in July",
            "p1-L6",
            category="reduction_in_income",
            financial_effect="hours and pay reduced",
        ),
        "other_reasons": [],
        "onset": item("in July", "p1-L6", as_stated="July", month="2026-07"),
        "duration": item(
            "I do not know whether my hours will return to 40 a week", "p1-L9", category="unknown"
        ),
        "intent": item("I want to keep my home", "p1-L14", category="keep"),
        "timeline": [],
        "enclosed_documents": [],
    }
    body.update(overrides)
    return HardshipProfile.model_validate(body)


def flags_by_path(p: HardshipProfile, **kwargs: int) -> dict[str, list[str]]:
    return {c.path: c.flags for c in verify_quotes(p, LETTER, **kwargs)}


def test_exact_quotes_pass() -> None:
    checks = verify_quotes(profile(), LETTER)
    assert [c.path for c in checks] == ["primary_reason", "onset", "duration", "intent"]
    assert all(c.verified for c in checks)


def test_paraphrase_wrong_line_and_unknown_line_fail() -> None:
    p = profile(
        primary_reason=item(
            "my hours were cut from 40 to 30",  # paraphrase
            "p1-L6",
            category="reduction_in_income",
            financial_effect="pay reduced",
        ),
        intent=item("I want to keep my home", "p1-L13", category="keep"),  # wrong line
        duration=item("I do not know", "p1-L9", "p1-L99", category="unknown"),  # unknown line
    )
    flags = flags_by_path(p)
    assert flags["primary_reason"] == [UNVERIFIED_QUOTE]
    assert flags["intent"] == [UNVERIFIED_QUOTE]
    assert flags["duration"] == [UNVERIFIED_QUOTE]
    assert flags["onset"] == []


def test_a_quote_may_run_across_lines_and_whitespace_is_normalised() -> None:
    p = profile(
        timeline=[
            item(
                "pay fell by a quarter.  I fell behind in August",
                "p1-L7",
                "p1-L6",  # cited out of order: read in document order
                when="August",
                event="Fell behind on payments",
            )
        ]
    )
    assert flags_by_path(p)["timeline[0]"] == []


def test_typographic_apostrophes_match_straight_ones() -> None:
    # The model straightened the letter's curly apostrophe when copying.
    p = profile(intent=item("I want to keep my home's garden", "p1-L14", category="keep"))
    lines = [*LETTER[:13], type(LETTER[13])(1, 14, "I want to keep my home\u2019s garden")]
    checks = {c.path: c for c in verify_quotes(p, lines)}
    assert checks["intent"].verified


def test_missing_quotes_and_long_quotes() -> None:
    p = profile(
        onset=item(None, as_stated=None, month=None),  # not stated: passes
        duration=item(None, "p1-L9", category="unknown"),  # lines without a quote: fails
    )
    flags = flags_by_path(p, max_quote_chars=30)
    assert flags["onset"] == []
    assert flags["duration"] == [UNVERIFIED_QUOTE]
    assert flags["primary_reason"] == [QUOTE_TOO_LONG]  # 41 characters, found but too long


def test_empty_quote_fails() -> None:
    p = profile(intent=item("  ", "p1-L14", category="keep"))
    assert flags_by_path(p)["intent"] == [UNVERIFIED_QUOTE]


# ---------- figures ----------


def test_numbers_in_ignores_digits_joined_to_letters() -> None:
    found = numbers_in("Box 12 code D 4,457.92 on p1-L31 for E-20417 in 2025; 5.49% and 401(k)")
    assert found == {
        Decimal("12"),
        Decimal("4457.92"),
        Decimal("2025"),
        Decimal("5.49"),
        Decimal("401"),
        Decimal("20417"),
    }


def test_check_figures_returns_numbers_not_in_the_inputs() -> None:
    allowed = numbers_in("Box 5 74,298.60 Box 1 69,840.68 gap 4,457.92 W-2 2025 Box 12 code D")
    text = (
        "Box 5 (74,298.60) exceeds Box 1 by 4,457.92, matching Box 12 code D in 2025, "
        "about 4,458 or 6.0% of wages."
    )
    assert check_figures(text, allowed) == ["4,458", "6.0"]


def test_check_figures_compares_values_not_spelling() -> None:
    assert check_figures("gap of 4457.920", ["4,457.92"]) == []
    assert check_figures("no figures here", []) == []


def test_decision_words() -> None:
    assert decision_words("The borrower is Eligible and may qualify; we approve.") == [
        "eligible",
        "qualify",
        "approve",
    ]
    assert decision_words("Qualifying income is determined by the underwriter.") == []
    assert decision_words("possible — to be confirmed") == []

"""Income calculations (Feature Design 2.3 to 2.5). Code does all the arithmetic (CLAUDE.md rule 1).

Everything here is pure ``Decimal``: no database, no model, no ``float``. Every function returns a
``Calc`` (its value, the formula, the inputs and the working as text) so "Show working" has
something to show, or a ``Check`` (a ``Calc`` plus whether the comparison passed and the figures a
flag message needs). Money is rounded half up to the cent at the last step only, and ratios to six
decimals; nothing is rounded between steps.

The settings (tolerance, decline threshold, history, pay frequencies) are read by
``app.services.analysis_config``; they arrive here as plain arguments.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from app.services.analysis_config import FrequencySpec
from app.services.normalize import display_amount

CENT = Decimal("0.01")
SIX_PLACES = Decimal("0.000001")
HUNDRED = Decimal(100)
TWELVE = Decimal(12)
DAYS_IN_YEAR = Decimal(365)

Evidence = dict[str, Any]


@dataclass(frozen=True)
class Calc:
    """One computed figure with its working."""

    name: str
    value: Decimal
    unit: str  # usd | ratio | count | days | months | match
    formula: str
    inputs: dict[str, str]
    working: str
    config_version: str
    evidence: tuple[Evidence, ...] = field(default=())


@dataclass(frozen=True)
class Check:
    """A comparison: the figure that was computed, whether it passed, and what a flag would say."""

    calc: Calc
    passed: bool
    details: dict[str, str]


# --- rounding and showing numbers -----------------------------------------------------------


def cents(value: Decimal) -> Decimal:
    return value.quantize(CENT, rounding=ROUND_HALF_UP)


def six_places(value: Decimal) -> Decimal:
    return value.quantize(SIX_PLACES, rounding=ROUND_HALF_UP)


def money(value: Decimal) -> str:
    """``Decimal("5980")`` -> ``"5,980.00"``."""
    return display_amount(value)


def plain(value: Decimal) -> str:
    """A quantity as printed (``"34.50"``): no exponent, no thousands separator."""
    return format(value, "f")


def percent(ratio: Decimal) -> str:
    """``Decimal("0.054901")`` -> ``"5.49%"`` (two decimals, half up)."""
    return f"{(ratio * HUNDRED).quantize(CENT, rounding=ROUND_HALF_UP)}%"


def _calc(
    name: str,
    value: Decimal,
    unit: str,
    formula: str,
    inputs: dict[str, Decimal | str],
    working: str,
    version: str,
    evidence: Sequence[Evidence],
) -> Calc:
    return Calc(
        name=name,
        value=value,
        unit=unit,
        formula=formula,
        inputs={key: plain(v) if isinstance(v, Decimal) else v for key, v in inputs.items()},
        working=working,
        config_version=version,
        evidence=tuple(evidence),
    )


def _need_positive(**values: Decimal) -> None:
    for name, value in values.items():
        if value <= 0:
            raise ValueError(f"{name} must be above zero, not {value}")


# --- monthly figures ------------------------------------------------------------------------


def base_pay_hourly(
    rate: Decimal,
    hours: Decimal,
    periods_per_year: int,
    *,
    version: str,
    evidence: Sequence[Evidence] = (),
) -> Calc:
    """Hourly base pay a month: rate x regular hours x pay periods per year / 12."""
    periods = Decimal(periods_per_year)
    _need_positive(rate=rate, hours=hours, periods_per_year=periods)
    value = cents(rate * hours * periods / TWELVE)
    return _calc(
        "base_pay_monthly",
        value,
        "usd",
        "rate x regular hours x periods per year / 12",
        {"rate": rate, "hours": hours, "periods_per_year": periods},
        f"{plain(rate)} x {plain(hours)} x {periods_per_year} / 12 = {money(value)}",
        version,
        evidence,
    )


def pay_from_current(
    name: str,
    current: Decimal,
    periods_per_year: int,
    *,
    version: str,
    evidence: Sequence[Evidence] = (),
) -> Calc:
    """A monthly figure from one period's amount: current x periods per year / 12.

    For a line printed without hours and rate (a salary), where the hourly formula has no inputs.
    """
    periods = Decimal(periods_per_year)
    _need_positive(periods_per_year=periods)
    value = cents(current * periods / TWELVE)
    return _calc(
        name,
        value,
        "usd",
        "current-period amount x periods per year / 12",
        {"current": current, "periods_per_year": periods},
        f"{money(current)} x {periods_per_year} / 12 = {money(value)}",
        version,
        evidence,
    )


def ytd_monthly_average(
    name: str,
    ytd: Decimal,
    periods_elapsed: int,
    periods_per_year: int,
    *,
    version: str,
    evidence: Sequence[Evidence] = (),
) -> Calc:
    """The year-to-date average a month: ytd x periods per year / (periods elapsed x 12)."""
    elapsed, periods = Decimal(periods_elapsed), Decimal(periods_per_year)
    _need_positive(periods_elapsed=elapsed, periods_per_year=periods)
    value = cents(ytd * periods / (elapsed * TWELVE))
    return _calc(
        name,
        value,
        "usd",
        "year-to-date amount x periods per year / (periods elapsed x 12)",
        {"ytd": ytd, "periods_per_year": periods, "periods_elapsed": elapsed},
        f"{money(ytd)} x {periods_per_year} / ({periods_elapsed} x 12) = {money(value)}",
        version,
        evidence,
    )


def annualized_pace(
    name: str,
    ytd: Decimal,
    periods_elapsed: int,
    periods_per_year: int,
    *,
    version: str,
    evidence: Sequence[Evidence] = (),
) -> Calc:
    """The year at the current pace: year-to-date amount x periods per year / periods elapsed."""
    elapsed, periods = Decimal(periods_elapsed), Decimal(periods_per_year)
    _need_positive(periods_elapsed=elapsed, periods_per_year=periods)
    value = cents(ytd * periods / elapsed)
    return _calc(
        name,
        value,
        "usd",
        "year-to-date amount x periods per year / periods elapsed",
        {"ytd": ytd, "periods_per_year": periods, "periods_elapsed": elapsed},
        f"{money(ytd)} x {periods_per_year} / {periods_elapsed} = {money(value)}",
        version,
        evidence,
    )


def ytd_per_period(
    name: str,
    ytd: Decimal,
    periods_elapsed: int,
    *,
    version: str,
    evidence: Sequence[Evidence] = (),
) -> Calc:
    """Year-to-date pay divided by the periods elapsed (Feature Design 2.5, "Year to date")."""
    elapsed = Decimal(periods_elapsed)
    _need_positive(periods_elapsed=elapsed)
    value = cents(ytd / elapsed)
    return _calc(
        name,
        value,
        "usd",
        "year-to-date amount / periods elapsed",
        {"ytd": ytd, "periods_elapsed": elapsed},
        f"{money(ytd)} / {periods_elapsed} = {money(value)}",
        version,
        evidence,
    )


def candidate_total(
    included: Sequence[tuple[str, Decimal]], *, version: str, evidence: Sequence[Evidence] = ()
) -> Calc:
    """The candidate monthly income: the monthly figures of the components that are included."""
    value = cents(sum((amount for _, amount in included), Decimal(0)))
    if included:
        terms = " + ".join(money(amount) for _, amount in included)
        named = ", ".join(label for label, _ in included)
        working = f"{terms} = {money(value)} ({named})"
    else:
        working = "No component is included = 0.00"
    return _calc(
        "candidate_monthly_income",
        value,
        "usd",
        "sum of the monthly figures of the included components",
        {label: amount for label, amount in included},
        working,
        version,
        evidence,
    )


# --- pay periods ----------------------------------------------------------------------------


def periods_elapsed(pay_date: date, periods_per_year: int) -> int:
    """Whole pay periods from 1 January to the pay date (day of the year x periods / 365, down).

    At least 1 (a pay date in the first days of January is the first period). The pay stub's own
    year-to-date figures are the cross-check (``periods_from_ytd``).
    """
    day_of_year = Decimal(pay_date.timetuple().tm_yday)
    whole = int(day_of_year * Decimal(periods_per_year) / DAYS_IN_YEAR)
    return max(1, whole)


def periods_elapsed_calc(
    pay_date: date, periods_per_year: int, *, version: str, evidence: Sequence[Evidence] = ()
) -> Calc:
    """``periods_elapsed`` as a figure with its working (it feeds every year-to-date average)."""
    value = periods_elapsed(pay_date, periods_per_year)
    day = pay_date.timetuple().tm_yday
    return _calc(
        "periods_elapsed",
        Decimal(value),
        "count",
        "day of the year x periods per year / 365, rounded down",
        {
            "pay_date": pay_date.isoformat(),
            "day_of_year": str(day),
            "periods_per_year": str(periods_per_year),
        },
        f"{pay_date.isoformat()} is day {day}; {day} x {periods_per_year} / 365 = {value} "
        "(rounded down)",
        version,
        evidence,
    )


def periods_from_ytd(ytd: Decimal, current: Decimal) -> Decimal | None:
    """Year-to-date divided by current-period pay: a whole number when pay does not vary."""
    return None if current <= 0 else (ytd / current).quantize(CENT, rounding=ROUND_HALF_UP)


def months_between(start: date, end: date) -> int:
    """Whole months from ``start`` to ``end`` (2026-01-01 to 2026-10-02 is 9)."""
    months = (end.year - start.year) * 12 + (end.month - start.month)
    return max(0, months - (1 if end.day < start.day else 0))


# --- comparisons ----------------------------------------------------------------------------


def variable_history_check(
    component: str,
    history_months: int,
    required_months: int,
    *,
    version: str,
    evidence: Sequence[Evidence] = (),
) -> Check:
    """Is the documented history of overtime, bonus or commission long enough to count it?"""
    passed = history_months >= required_months
    calc = _calc(
        f"{component}_history_months",
        Decimal(history_months),
        "months",
        "documented history in months against the requirement",
        {"history_months": Decimal(history_months), "required_months": Decimal(required_months)},
        f"{history_months} months documented, {required_months} required: "
        + ("enough" if passed else "not enough"),
        version,
        evidence,
    )
    return Check(
        calc, passed, {"history": f"{history_months} months", "required": str(required_months)}
    )


def wages_vs_w2_box1(
    tax_wages: Decimal,
    box1: Decimal,
    tolerance: Decimal,
    *,
    version: str,
    evidence: Sequence[Evidence] = (),
) -> Check:
    """Form 1040 wages against W-2 Box 1 for the same year, within the tolerance."""
    difference = abs(tax_wages - box1)
    passed = difference <= tolerance
    calc = _calc(
        "wages_vs_w2_box1_difference",
        cents(difference),
        "usd",
        "|Form 1040 wages - W-2 Box 1|",
        {"tax_wages": tax_wages, "box1": box1, "tolerance": tolerance},
        f"|{money(tax_wages)} - {money(box1)}| = {money(difference)} "
        f"(tolerance {money(tolerance)})",
        version,
        evidence,
    )
    return Check(
        calc,
        passed,
        {
            "tax_wages": money(tax_wages),
            "box1": money(box1),
            "difference": money(difference),
            "tolerance": money(tolerance),
        },
    )


_COMPANY_SUFFIX_PUNCTUATION = ",.;:"


def _employer_key(name: str, suffixes: Sequence[str]) -> str:
    words = [
        w.strip(_COMPANY_SUFFIX_PUNCTUATION).lower() for w in name.replace("&", " and ").split()
    ]
    words = [w for w in words if w]
    drop = {s.lower() for s in suffixes}
    while words and words[-1] in drop:
        words.pop()
    return " ".join("".join(ch for ch in w if ch.isalnum()) for w in words)


def employer_key(name: str, suffixes: Sequence[str]) -> str:
    """An employer's name as compared in code: case, punctuation and a trailing suffix dropped."""
    return _employer_key(name, suffixes)


def employer_match(
    stub_employer: str,
    w2_employer: str,
    suffixes: Sequence[str],
    *,
    version: str,
    evidence: Sequence[Evidence] = (),
) -> Check:
    """Is the employer on the latest pay stub the employer on the latest W-2?

    Names are compared in code after dropping case, punctuation and a trailing company suffix.
    """
    key_a, key_b = _employer_key(stub_employer, suffixes), _employer_key(w2_employer, suffixes)
    passed = bool(key_a) and key_a == key_b
    calc = _calc(
        "employer_match",
        Decimal(1 if passed else 0),
        "match",
        "latest pay stub employer = latest W-2 employer",
        {"stub_employer": stub_employer, "w2_employer": w2_employer},
        f"'{stub_employer}' and '{w2_employer}': " + ("same employer" if passed else "different"),
        version,
        evidence,
    )
    return Check(calc, passed, {"stub_employer": stub_employer, "w2_employer": w2_employer})


def deferral_gap(
    box5: Decimal,
    box1: Decimal,
    deferrals: Decimal,
    codes: Sequence[str],
    tolerance: Decimal,
    *,
    version: str,
    evidence: Sequence[Evidence] = (),
) -> Check:
    """W-2 Box 5 minus Box 1 against the Box 12 deferral codes.

    ``passed`` means the gap is explained: it equals the deferrals within the tolerance. A gap of
    zero with no deferrals is also explained (nothing to flag; the service says nothing).
    """
    gap = box5 - box1
    passed = abs(gap - deferrals) <= tolerance
    calc = _calc(
        "box5_minus_box1",
        cents(gap),
        "usd",
        "W-2 Box 5 - W-2 Box 1, against the Box 12 deferral codes",
        {"box5": box5, "box1": box1, "deferrals": deferrals, "tolerance": tolerance},
        f"{money(box5)} - {money(box1)} = {money(gap)}; deferrals {money(deferrals)} "
        f"(tolerance {money(tolerance)})",
        version,
        evidence,
    )
    return Check(
        calc,
        passed,
        {
            "gap": money(gap),
            "deferrals": money(deferrals),
            "codes": ", ".join(codes) if codes else "none",
        },
    )


def yoy_trend(
    label: str,
    from_label: str,
    from_amount: Decimal,
    to_label: str,
    to_amount: Decimal,
    decline_threshold: Decimal,
    *,
    version: str,
    evidence: Sequence[Evidence] = (),
) -> Check:
    """The change from one figure to a later one, and whether it is a decline above the threshold.

    ``passed`` is False only for a drop above the threshold (Feature Design 2.3: a year-over-year
    drop above 5% is flagged). The trend sentence is built from these numbers by a template.
    """
    _need_positive(**{from_label: from_amount})
    change = six_places((to_amount - from_amount) / from_amount)
    declined = -change > decline_threshold
    calc = _calc(
        f"{label.lower().replace(' ', '_')}_change",
        change,
        "ratio",
        "(later - earlier) / earlier",
        {"earlier": from_amount, "later": to_amount, "decline_threshold": decline_threshold},
        f"({money(to_amount)} - {money(from_amount)}) / {money(from_amount)} = {percent(change)}",
        version,
        evidence,
    )
    details = {
        "label": label,
        "direction": "rose" if change >= 0 else "fell",
        "change": percent(abs(change)),
        "drop": percent(-change) if change < 0 else "0.00%",
        "from_label": from_label,
        "from_amount": money(from_amount),
        "to_label": to_label,
        "to_amount": money(to_amount),
        "threshold": percent(decline_threshold),
    }
    return Check(calc, not declined, details)


def pay_frequency_check(
    printed: str,
    spec: FrequencySpec,
    period_start: date,
    period_end: date,
    *,
    version: str,
    evidence: Sequence[Evidence] = (),
) -> Check:
    """The printed pay frequency against the frequency the pay period's length implies."""
    days = (period_end - period_start).days + 1  # inclusive: 14 days from the 14th to the 27th
    passed = spec.min_days <= days <= spec.max_days
    calc = _calc(
        "pay_period_days",
        Decimal(days),
        "days",
        "pay period end - pay period start + 1",
        {"period_start": period_start.isoformat(), "period_end": period_end.isoformat()},
        f"{period_end.isoformat()} - {period_start.isoformat()} + 1 = {days} days; "
        f"{printed} pay is {spec.min_days}"
        + ("" if spec.min_days == spec.max_days else f" to {spec.max_days}")
        + " days",
        version,
        evidence,
    )
    return Check(calc, passed, {"printed": printed, "days": str(days)})


def ytd_vs_current(
    component: str,
    ytd_average: Decimal,
    current: Decimal,
    tolerance: Decimal,
    *,
    version: str,
    evidence: Sequence[Evidence] = (),
) -> Check:
    """Year-to-date pay per period against current-period pay, within the tolerance."""
    difference = abs(ytd_average - current)
    passed = difference <= tolerance
    calc = _calc(
        f"{component.lower().replace(' ', '_')}_ytd_vs_current",
        cents(difference),
        "usd",
        "|year-to-date per period - current period|",
        {"ytd_average": ytd_average, "current": current, "tolerance": tolerance},
        f"|{money(ytd_average)} - {money(current)}| = {money(difference)} "
        f"(tolerance {money(tolerance)})",
        version,
        evidence,
    )
    return Check(
        calc,
        passed,
        {
            "component": component,
            "average": money(ytd_average),
            "current": money(current),
            "difference": money(difference),
        },
    )

"""Income analysis (Feature Design 2): the components, the checks and the candidate monthly income.

``analyze`` is pure: documents (as ``case_facts.DocFacts``) and settings in, components, figures and
flags out. No database, no model, no ``float``. The arithmetic is ``app.services.calculations``;
this module decides which figures go into which formula and which comparisons to make.

What it does, in the Feature Design's order:

* groups each earnings line into base, overtime, bonus or commission by its description;
* base pay is rate x regular hours x periods per year / 12 (or, for a salary, the period amount);
* overtime, bonus and commission are the year-to-date average a month, and count only with enough
  documented history (24 months in the sample), otherwise they are excluded with the reason;
* cross-checks the documents: 1040 wages against W-2 Box 1, the employer on the latest stub against
  the latest W-2, Box 5 minus Box 1 against the Box 12 deferral codes, the latest full-year W-2
  against the current year at its pace, year-to-date pay against the current period, and the
  printed pay frequency against the length of the pay period;
* a check that cannot run (an input is missing) says so as an info flag; it never guesses.

Every figure is a ``Calc`` carrying the document fields it came from (rule 2). The underwriter
decides what counts: this only suggests a candidate.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field, replace
from datetime import date
from decimal import Decimal
from typing import Any

from app.services.analysis_config import AnalysisConfig, FrequencySpec
from app.services.calculations import (
    Calc,
    Check,
    Evidence,
    annualized_pace,
    base_pay_hourly,
    candidate_total,
    deferral_gap,
    employer_key,
    employer_match,
    months_between,
    pay_frequency_check,
    pay_from_current,
    periods_elapsed_calc,
    periods_from_ytd,
    variable_history_check,
    wages_vs_w2_box1,
    yoy_trend,
    ytd_monthly_average,
    ytd_per_period,
    ytd_vs_current,
)
from app.services.case_facts import DocFacts, FieldFact
from app.services.document_config import get_document_fields

KIND_LABELS = {
    "base": "Base pay",
    "overtime": "Overtime",
    "bonus": "Bonus",
    "commission": "Commission",
}
ONE_CENT_QUANT = Decimal("0.01")


@dataclass(frozen=True)
class ComponentResult:
    borrower: str
    employer: str | None
    kind: str
    current_period: Decimal | None
    ytd: Decimal | None
    monthly: Decimal
    included: bool
    exclusion_reason: str | None
    calc: Calc


@dataclass(frozen=True)
class FlagResult:
    code: str
    key: str  # tells two flags of one code apart (one per tax year, for example)
    severity: str
    message: str
    evidence: tuple[Evidence, ...] = ()
    working: str | None = None


@dataclass
class IncomeOutcome:
    components: list[ComponentResult]
    calcs: list[Calc]  # every figure, the components' own and the candidate total last
    flags: list[FlagResult]
    candidate: Calc
    notes: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class _Row:
    description: str | None
    hours: Decimal | None
    rate: Decimal | None
    current: Decimal | None
    ytd: Decimal | None
    facts: tuple[FieldFact, ...]


def _year(text: str | None) -> int | None:
    found = re.search(r"\b(19|20)\d{2}\b", text or "")
    return int(found.group(0)) if found else None


def _people_key(name: str | None) -> str:
    return " ".join(sorted(re.findall(r"[a-z0-9]+", (name or "").lower())))


def _sum(values: list[Decimal | None]) -> Decimal | None:
    """The sum when every value is there, else None (a partial sum would understate)."""
    if not values or any(v is None for v in values):
        return None
    return sum((v for v in values if v is not None), Decimal(0))


class _Analysis:
    def __init__(self, docs: list[DocFacts], cfg: AnalysisConfig) -> None:
        self.cfg = cfg
        self.inc = cfg.income
        self.thr = cfg.thresholds
        self.version = cfg.calc_version("income_method", "thresholds")
        self.fields_cfg = get_document_fields()
        self.docs = [d for d in docs if d.usable and d.fields]
        self.calcs: list[Calc] = []
        self.flags: list[FlagResult] = []
        self.components: list[ComponentResult] = []
        self.notes: list[str] = []
        self._cannot: dict[str, tuple[str, list[str]]] = {}
        self._stubs_seen = 0

    # --- output ------------------------------------------------------------------------------

    def add(self, calc: Calc) -> Calc:
        self.calcs.append(calc)
        return calc

    def flag(
        self,
        code: str,
        key: str,
        evidence: list[Evidence],
        working: str | None = None,
        *,
        template: str | None = None,
        **values: object,
    ) -> None:
        severity, message = self.inc.flag(template or code, **values)
        self.flags.append(FlagResult(code, key, severity, message, tuple(evidence), working))

    def cannot_check(self, code: str, rule: str, missing: str) -> None:
        known, names = self._cannot.setdefault(code, (rule, []))
        if missing not in names:
            names.append(missing)
        self._cannot[code] = (known, names)

    def flush_cannot_checks(self) -> None:
        for code, (rule, names) in self._cannot.items():
            self.flag(
                code,
                f"{code}-cannot",
                [],
                template="cannot_check",
                rule=rule,
                missing=", ".join(names),
            )

    @staticmethod
    def ev(doc: DocFacts, *facts: FieldFact | None) -> list[Evidence]:
        return [
            {"document_id": str(doc.id), "field": f.name, "line_ids": list(f.lines)}
            for f in facts
            if f is not None
        ]

    def fact(self, doc: DocFacts, name: str) -> FieldFact | None:
        return doc.fields.get(name)

    # --- pay stubs ---------------------------------------------------------------------------

    def latest_stubs(self) -> list[DocFacts]:
        """The latest pay stub of each employee and employer."""
        latest: dict[tuple[str, str], DocFacts] = {}
        suffixes = self.inc.employer_suffixes.value

        def order(d: DocFacts) -> tuple[date, date, Any]:
            return (
                d.day("pay_period_end") or date.min,
                d.day("pay_date") or date.min,
                d.created_at,
            )

        for doc in self.docs:
            if doc.doc_type != "pay_stub":
                continue
            key = (
                _people_key(doc.text("employee_name")),
                employer_key(doc.text("employer_name") or "", suffixes),
            )
            if key not in latest or order(doc) > order(latest[key]):
                latest[key] = doc
        return sorted(latest.values(), key=order)

    def earnings_rows(self, doc: DocFacts) -> list[_Row]:
        rows: list[_Row] = []
        for parts in doc.rows("earnings_").values():
            description = parts.get("description")
            rows.append(
                _Row(
                    description.text if description else None,
                    _number(parts.get("hours")),
                    _number(parts.get("rate")),
                    _amount(parts.get("current")),
                    _amount(parts.get("ytd")),
                    tuple(parts.values()),
                )
            )
        if rows:
            return rows
        # The rule-based reader names a line earnings_<kind>_current and reads nothing more.
        for name, fact in doc.fields.items():
            if self.fields_cfg.is_earnings_field("pay_stub", name):
                word = name[len("earnings_") : -len("_current")]
                rows.append(_Row(word, None, None, _amount(fact), None, (fact,)))
        return rows

    def frequency_of(self, doc: DocFacts) -> tuple[str, FrequencySpec, str] | None:
        """The pay frequency: the printed one, else the one the pay period's length implies."""
        printed = doc.text("pay_frequency")
        found = self.inc.frequency_for(printed)
        if found is not None:
            return found[0], found[1], printed or found[0]
        start, end = doc.day("pay_period_start"), doc.day("pay_period_end")
        if start is None or end is None:
            return None
        days = (end - start).days + 1
        fits = [
            (spec.max_days - spec.min_days, name, spec)
            for name, spec in self.inc.pay_frequencies.value.items()
            if spec.min_days <= days <= spec.max_days
        ]
        if not fits:
            return None
        _, name, spec = min(fits, key=lambda f: (f[0], f[1]))
        return name, spec, name.replace("_", "-")

    def stub(self, doc: DocFacts, ordinal: int) -> dict[str, Any] | None:
        """Components, checks and flags for one pay stub. Returns the figures later checks reuse."""
        employee = doc.text("employee_name") or doc.borrower or "Borrower"
        employer = doc.text("employer_name")
        start, end, pay = (
            doc.day("pay_period_start"),
            doc.day("pay_period_end"),
            doc.day("pay_date"),
        )
        suffix = "" if ordinal == 0 else f"_{ordinal + 1}"

        frequency = self.frequency_of(doc)
        if frequency is None:
            self.cannot_check("INC-W103", "the pay frequency", "a pay frequency or a pay period")
            return None
        _, spec, printed = frequency
        ppy = spec.periods_per_year
        printed_fact = self.fact(doc, "pay_frequency")
        if self.inc.frequency_for(doc.text("pay_frequency")) is not None and start and end:
            check = pay_frequency_check(
                printed,
                spec,
                start,
                end,
                version=self.version,
                evidence=self.ev(
                    doc,
                    printed_fact,
                    self.fact(doc, "pay_period_start"),
                    self.fact(doc, "pay_period_end"),
                ),
            )
            self.add(check.calc)
            if not check.passed:
                self.flag(
                    "INC-W103",
                    f"frequency{suffix}",
                    list(check.calc.evidence),
                    check.calc.working,
                    **check.details,
                )

        when = pay or end
        elapsed: int | None = None
        if when is None:
            self.cannot_check("INC-W102", "year-to-date pay", "the pay date")
        else:
            elapsed_calc = self.add(
                periods_elapsed_calc(
                    when,
                    ppy,
                    version=self.version,
                    evidence=self.ev(
                        doc, self.fact(doc, "pay_date") or self.fact(doc, "pay_period_end")
                    ),
                )
            )
            elapsed = int(elapsed_calc.value)

        rows = self.earnings_rows(doc)
        by_kind: dict[str, list[_Row]] = {}
        for row in rows:
            kind = self.inc.component_for(row.description)
            if kind is None:
                self.flag(
                    "INC-W105",
                    f"earnings-{len(self.flags)}{suffix}",
                    self.ev(doc, *row.facts),
                    description=row.description or "(no description)",
                )
                continue
            by_kind.setdefault(kind, []).append(row)

        self._cross_check_periods(doc, by_kind.get("base", []), elapsed, ppy, suffix)

        year = (when or end or start or date.min).year  # the year of the stub's own dates
        for kind in self.inc.components:
            kind_rows = by_kind.get(kind)
            if not kind_rows:
                continue
            self._component(
                doc, employee, employer, kind, kind_rows, elapsed, ppy, year, when, suffix
            )

        gross_ytd_fact, gross_fact = (
            self.fact(doc, "gross_pay_ytd"),
            self.fact(doc, "gross_pay_current"),
        )
        gross_ytd, gross = doc.amount("gross_pay_ytd"), doc.amount("gross_pay_current")
        pace: Calc | None = None
        if gross_ytd is not None and elapsed:
            evidence = self.ev(doc, gross_ytd_fact)
            pace = self.add(
                annualized_pace(
                    f"gross_pay_pace_{year}",
                    gross_ytd,
                    elapsed,
                    ppy,
                    version=self.version,
                    evidence=evidence,
                )
            )
            if gross is not None:
                average = self.add(
                    ytd_per_period(
                        "gross_pay_ytd_per_period",
                        gross_ytd,
                        elapsed,
                        version=self.version,
                        evidence=evidence,
                    )
                )
                check = ytd_vs_current(
                    "Gross pay",
                    average.value,
                    gross,
                    self.thr.tolerance_for(average.value, gross),
                    version=self.version,
                    evidence=self.ev(doc, gross_ytd_fact, gross_fact),
                )
                self.add(check.calc)
                if not check.passed:
                    self.flag(
                        "INC-W102",
                        f"ytd{suffix}",
                        list(check.calc.evidence),
                        check.calc.working,
                        **check.details,
                    )
        else:
            self.cannot_check(
                "INC-W102", "year-to-date pay", "gross pay year to date or the pay date"
            )
        return {"doc": doc, "pace": pace, "year": year, "ppy": ppy, "elapsed": elapsed}

    def _cross_check_periods(
        self, doc: DocFacts, base_rows: list[_Row], elapsed: int | None, ppy: int, suffix: str
    ) -> None:
        """The pay date's pay period against regular year-to-date divided by regular current."""
        if elapsed is None:
            return
        for row in base_rows:
            if row.ytd is None or row.current is None:
                continue
            ratio = periods_from_ytd(row.ytd, row.current)
            if ratio is not None and ratio == ratio.to_integral_value() and int(ratio) != elapsed:
                self.flag(
                    "INC-W104",
                    f"periods{suffix}",
                    self.ev(doc, *row.facts),
                    by_date=str(elapsed),
                    by_ytd=str(ratio),
                )
            return

    def _component(
        self,
        doc: DocFacts,
        employee: str,
        employer: str | None,
        kind: str,
        rows: list[_Row],
        elapsed: int | None,
        ppy: int,
        year: int,
        when: date | None,
        suffix: str,
    ) -> None:
        facts = tuple(f for r in rows for f in r.facts)
        evidence = self.ev(doc, *facts)
        current = _sum([r.current for r in rows])
        ytd = _sum([r.ytd for r in rows])
        name = f"{kind}_monthly{suffix}"
        monthly: Calc | None = None
        if kind == "base":
            hourly = next(
                (r for r in rows if r.hours and r.rate and r.hours > 0 and r.rate > 0), None
            )
            if hourly is not None and hourly.hours is not None and hourly.rate is not None:
                monthly = base_pay_hourly(
                    hourly.rate,
                    hourly.hours,
                    ppy,
                    version=self.version,
                    evidence=self.ev(doc, *hourly.facts),
                )
            elif current is not None:
                monthly = pay_from_current(
                    name, current, ppy, version=self.version, evidence=evidence
                )
        else:
            if ytd is not None and elapsed:
                monthly = ytd_monthly_average(
                    name, ytd, elapsed, ppy, version=self.version, evidence=evidence
                )
            elif current is not None:
                monthly = pay_from_current(
                    name, current, ppy, version=self.version, evidence=evidence
                )
        if monthly is None:
            self.cannot_check(
                "INC-W102", f"the {KIND_LABELS[kind].lower()} figure", "an amount for this period"
            )
            return
        monthly = replace(monthly, name=name)
        self.add(monthly)

        included, reason = True, None
        if kind != "base":
            if when is None:
                included, reason = False, None
                self.cannot_check(
                    "INC-W101", "the history of overtime, bonus and commission", "the pay date"
                )
            else:
                history = months_between(date(year, 1, 1), when)
                required = self.inc.variable_history_months.value
                check = variable_history_check(
                    kind, history, required, version=self.version, evidence=evidence
                )
                self.add(check.calc)
                if not check.passed:
                    included = False
                    severity, reason = self.inc.flag(
                        "INC-W101",
                        component=KIND_LABELS[kind],
                        history=f"{history} months ({year} only)",
                        required=required,
                    )
                    self.flags.append(
                        FlagResult(
                            "INC-W101",
                            f"history-{kind}{suffix}",
                            severity,
                            reason,
                            tuple(evidence),
                            check.calc.working,
                        )
                    )
            if reason is None and not included:
                reason = "The documented history could not be worked out."
        self.components.append(
            ComponentResult(
                employee,
                employer,
                kind,
                _cents(current),
                _cents(ytd),
                monthly.value,
                included,
                reason,
                monthly,
            )
        )

    # --- W-2 and Form 1040 -------------------------------------------------------------------

    def tax_documents(self) -> tuple[dict[int, DocFacts], dict[int, DocFacts]]:
        """The W-2 and the 1040 for each tax year (the latest upload if there are two)."""
        w2s: dict[int, DocFacts] = {}
        returns: dict[int, DocFacts] = {}
        for doc in self.docs:
            year = _year(doc.text("tax_year"))
            if year is None:
                continue
            target = (
                w2s
                if doc.doc_type == "w2"
                else returns
                if doc.doc_type == "tax_return_1040"
                else None
            )
            if target is not None and (
                year not in target or doc.created_at > target[year].created_at
            ):
                target[year] = doc
        return w2s, returns

    def cross_documents(self, stubs: list[dict[str, Any]]) -> None:
        w2s, returns = self.tax_documents()
        suffixes = self.inc.employer_suffixes.value
        codes = [c.upper() for c in self.inc.deferral_codes.value]

        # The annual history: what each W-2 and return printed.
        for year in sorted(set(w2s) | set(returns)):
            w2, tax = w2s.get(year), returns.get(year)
            for label, doc, field_name in (
                ("w2_box1", w2, "box1_wages"),
                ("w2_box5", w2, "box5_medicare_wages"),
                ("wages_1040", tax, "wages"),
            ):
                amount = doc.amount(field_name) if doc else None
                if doc is not None and amount is not None:
                    self.add(_printed(f"{label}_{year}", amount, doc, field_name, self.version))

        # Form 1040 wages against W-2 Box 1, per year.
        paired = sorted(set(w2s) & set(returns))
        if not paired:
            self.cannot_check(
                "INC-CHK-01",
                "Form 1040 wages against W-2 Box 1",
                "a W-2 and a Form 1040 for the same year",
            )
        for year in paired:
            w2, tax = w2s[year], returns[year]
            box1, wages = w2.amount("box1_wages"), tax.amount("wages")
            if box1 is None or wages is None:
                self.cannot_check(
                    "INC-CHK-01", "Form 1040 wages against W-2 Box 1", f"{year} wages and Box 1"
                )
                continue
            check = wages_vs_w2_box1(
                wages,
                box1,
                self.thr.tolerance_for(wages, box1),
                version=self.version,
                evidence=self.ev(tax, tax.fields.get("wages"))
                + self.ev(w2, w2.fields.get("box1_wages")),
            )
            self.add(check.calc)
            if not check.passed:
                self.flag(
                    "INC-CHK-01",
                    f"wages-{year}",
                    list(check.calc.evidence),
                    check.calc.working,
                    year=year,
                    **check.details,
                )

        # Box 5 minus Box 1 against the Box 12 deferral codes, per W-2.
        if not w2s:
            self.cannot_check(
                "INC-CHK-03", "W-2 Box 5 minus Box 1 against the Box 12 deferrals", "a W-2"
            )
        for year, w2 in sorted(w2s.items()):
            box5, box1 = w2.amount("box5_medicare_wages"), w2.amount("box1_wages")
            if box5 is None or box1 is None:
                self.cannot_check(
                    "INC-CHK-03",
                    "W-2 Box 5 minus Box 1 against the Box 12 deferrals",
                    f"{year} Box 1 and Box 5",
                )
                continue
            deferrals = Decimal(0)
            facts: list[FieldFact | None] = [
                w2.fields.get("box1_wages"),
                w2.fields.get("box5_medicare_wages"),
            ]
            for parts in w2.rows("box12_").values():
                code, amount = parts.get("code"), _amount(parts.get("amount"))
                if code and (code.text or "").strip().upper() in codes and amount is not None:
                    deferrals += amount
                    facts += [code, parts.get("amount")]
            check = deferral_gap(
                box5,
                box1,
                deferrals,
                codes,
                self.thr.tolerance_for(box5 - box1, deferrals),
                version=self.version,
                evidence=self.ev(w2, *facts),
            )
            self.add(check.calc)
            if box5 == box1 and deferrals == 0:
                continue  # no gap and nothing to explain: nothing to say
            self.flag(
                "INC-CHK-03",
                f"deferrals-{year}",
                list(check.calc.evidence),
                check.calc.working,
                template="INC-CHK-03:explained" if check.passed else None,
                year=year,
                **check.details,
            )

        # The employer on the latest pay stub against the latest W-2.
        if stubs and w2s:
            stub_doc = stubs[-1]["doc"]
            latest_w2 = w2s[max(w2s)]
            a, b = stub_doc.text("employer_name"), latest_w2.text("employer_name")
            if a and b:
                check = employer_match(
                    a,
                    b,
                    suffixes,
                    version=self.version,
                    evidence=self.ev(stub_doc, stub_doc.fields.get("employer_name"))
                    + self.ev(latest_w2, latest_w2.fields.get("employer_name")),
                )
                self.add(check.calc)
                if not check.passed:
                    self.flag(
                        "INC-CHK-02",
                        "employer",
                        list(check.calc.evidence),
                        check.calc.working,
                        **check.details,
                    )
            else:
                self.cannot_check(
                    "INC-CHK-02", "the employer on the pay stub against the W-2", "an employer name"
                )
        else:
            self.cannot_check(
                "INC-CHK-02", "the employer on the pay stub against the W-2", "a pay stub and a W-2"
            )

        # The trend: the latest full-year W-2 against the current year at its pace, and W-2 to W-2.
        paced = next((s for s in reversed(stubs) if s["pace"] is not None), None)
        threshold = self.thr.decline_threshold.value
        if w2s:
            last_year = max(w2s)
            last = w2s[last_year]
            box5 = last.amount("box5_medicare_wages")
            if box5 is not None and paced is not None and paced["year"] == last_year + 1:
                pace: Calc = paced["pace"]
                check = yoy_trend(
                    "Medicare wages",
                    str(last_year),
                    box5,
                    f"the {paced['year']} pace",
                    pace.value,
                    threshold,
                    version=self.version,
                    evidence=self.ev(last, last.fields.get("box5_medicare_wages"))
                    + list(pace.evidence),
                )
                self.add(check.calc)
                self._trend_flag("trend-current", check)
            else:
                self.cannot_check(
                    "INC-CHK-04",
                    "the income trend",
                    "a W-2 for the year before the pay stub and its year-to-date pay",
                )
            before = w2s.get(last_year - 1)
            if (
                before is not None
                and box5 is not None
                and before.amount("box5_medicare_wages") is not None
            ):
                earlier = before.amount("box5_medicare_wages")
                if earlier is not None:
                    check = yoy_trend(
                        "Medicare wages",
                        str(last_year - 1),
                        earlier,
                        str(last_year),
                        box5,
                        threshold,
                        version=self.version,
                        evidence=self.ev(before, before.fields.get("box5_medicare_wages"))
                        + self.ev(last, last.fields.get("box5_medicare_wages")),
                    )
                    self.add(check.calc)
                    self._trend_flag("trend-w2", check)
        else:
            self.cannot_check("INC-CHK-04", "the income trend", "a W-2")

    def _trend_flag(self, key: str, check: Check) -> None:
        self.flag(
            "INC-CHK-04",
            key,
            list(check.calc.evidence),
            check.calc.working,
            template=None if not check.passed else "INC-CHK-04:trend",
            **check.details,
        )

    # --- the whole analysis ------------------------------------------------------------------

    def run(self) -> IncomeOutcome:
        latest = self.latest_stubs()
        stubs = [s for i, doc in enumerate(latest) if (s := self.stub(doc, i)) is not None]
        if not latest:
            self.cannot_check("INC-W103", "the pay frequency", "a pay stub")
        self.cross_documents(stubs)
        included = [(KIND_LABELS[c.kind], c.monthly) for c in self.components if c.included]
        candidate = self.add(candidate_total(included, version=self.version))
        self.flush_cannot_checks()
        return IncomeOutcome(self.components, self.calcs, self.flags, candidate, self.notes)


# --- helpers --------------------------------------------------------------------------------


def _amount(fact: FieldFact | None) -> Decimal | None:
    from app.services.normalize import parse_amount

    return parse_amount(fact.text) if fact else None


def _number(fact: FieldFact | None) -> Decimal | None:
    from app.services.normalize import parse_number

    return parse_number(fact.text) if fact else None


def _cents(value: Decimal | None) -> Decimal | None:
    return None if value is None else value.quantize(ONE_CENT_QUANT)


def _printed(name: str, amount: Decimal, doc: DocFacts, field_name: str, version: str) -> Calc:
    """A figure as printed on a document: not computed, but kept with where it was read."""
    from app.services.calculations import money

    label = name.replace("_", " ")
    return Calc(
        name=name,
        value=amount,
        unit="usd",
        formula="as printed on the document",
        inputs={field_name: str(amount)},
        working=f"{label} = {money(amount)}",
        config_version=version,
        evidence=tuple(_Analysis.ev(doc, doc.fields.get(field_name))),
    )


def analyze(docs: list[DocFacts], cfg: AnalysisConfig) -> IncomeOutcome:
    """The income analysis of a case's documents."""
    return _Analysis(docs, cfg).run()


def flag_entity_id(run_id: uuid.UUID, code: str, key: str) -> uuid.UUID:
    """A stable id for one flag of one run, so re-saving a run cannot make a second flag."""
    return uuid.uuid5(run_id, f"{code}:{key}")

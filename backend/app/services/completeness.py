"""Completeness checking (Feature Design 1.2 step 5, FSD section 7): documents against a checklist.

Pure: documents (``case_facts.DocFacts``), the case's profile and a checklist in, a status for each
item out. Code decides every status; the checklist values are illustrative samples. It is never a
loan decision.

Each item gets the first status whose condition holds (FSD section 7):

1. **missing**      no usable document of the required type for the borrower or account;
2. **needs review** a needed field was not found, the owner is uncertain, or a document is dated
                    after the reference date;
3. **partial**      documents exist but coverage is short, a year is absent, the latest date is
                    too old, or a document is incomplete;
4. **satisfied**    everything required is met.

Days are counted inclusively, and overlapping or adjacent ranges are one continuous span: stubs for
2026-09-14 to 09-27 and 09-28 to 10-11 are one 28-day span. N months of coverage means the end date
is on or after the start plus N months minus a day. Overall: incomplete if any item is missing or
partial; otherwise needs review if any item needs review; otherwise complete. An override (a
person's, with a reason) counts as satisfied and never replaces the computed status.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any, Literal

from app.services.analysis_config import Checklist, ChecklistItem, ChecklistsConfig
from app.services.case_facts import DocFacts

Status = Literal["satisfied", "needs_review", "partial", "missing"]
Overall = Literal["complete", "incomplete", "needs_review"]

# What an open document flag means for completeness. DI-W701: a page is missing or a table is cut
# off (the document says it has more than was uploaded).
INCOMPLETE_FLAGS = {"DI-W701": "a page is missing or a table is cut off"}
MAX_MONTHS = 120


@dataclass(frozen=True)
class Profile:
    """What the case's profile says: who the borrower is, and as of when."""

    borrower_names: list[str]
    reference_date: date


@dataclass
class ItemResult:
    item_id: str
    label: str
    status: Status  # what code computed; an override sits beside it and never replaces it
    reason: str
    document_ids: list[str] = field(default_factory=list)
    override: dict[str, Any] | None = None  # {"reason", "by", "at"}

    @property
    def effective(self) -> str:
        """``overridden`` while a person's override stands, else the computed status."""
        return "overridden" if self.override else self.status

    def as_json(self) -> dict[str, Any]:
        return {
            "item_id": self.item_id,
            "label": self.label,
            "status": self.status,
            "reason": self.reason,
            "document_ids": list(self.document_ids),
            "override": self.override,
        }

    @staticmethod
    def from_json(data: dict[str, Any]) -> ItemResult:
        return ItemResult(
            data["item_id"],
            data["label"],
            data["status"],
            data["reason"],
            list(data.get("document_ids", [])),
            data.get("override"),
        )


@dataclass
class CompletenessOutcome:
    items: list[ItemResult]
    overall: Overall
    outstanding: list[str]


# --- dates ----------------------------------------------------------------------------------


def add_months(day: date, months: int) -> date:
    """``2026-01-31`` plus one month is ``2026-02-28``: the day is kept where the month has it."""
    index = day.year * 12 + (day.month - 1) + months
    year, month = divmod(index, 12)
    month += 1
    for last in (31, 30, 29, 28):
        try:
            return date(year, month, min(day.day, last))
        except ValueError:
            continue
    raise ValueError("unreachable")  # pragma: no cover


def merge_ranges(ranges: list[tuple[date, date]]) -> list[tuple[date, date]]:
    """Overlapping or adjacent ranges as continuous spans, oldest first."""
    merged: list[tuple[date, date]] = []
    for start, end in sorted(ranges):
        if merged and start <= merged[-1][1] + timedelta(days=1):
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return merged


def span_days(span: tuple[date, date]) -> int:
    return (span[1] - span[0]).days + 1


def longest(spans: list[tuple[date, date]]) -> tuple[date, date] | None:
    return max(spans, key=span_days, default=None)


def months_covered(span: tuple[date, date]) -> int:
    """Whole months a span covers: the end is on or after start + N months - 1 day."""
    start, end = span
    covered = 0
    while covered < MAX_MONTHS and end >= add_months(start, covered + 1) - timedelta(days=1):
        covered += 1
    return covered


# --- who a document is about ----------------------------------------------------------------


def name_tokens(text: str | None) -> set[str]:
    """Words of a name, lower case, without initials: ``"REYES, DANIEL A."`` -> daniel, reyes."""
    return {w for w in re.findall(r"[a-z0-9]+", (text or "").lower()) if len(w) > 1}


def owner_of(doc: DocFacts, borrower_names: list[str]) -> Literal["matched", "other", "unknown"]:
    """Does this document belong to a borrower on the profile? Compared in code, never guessed.

    A profile name matches when every word of it is in the document's name (a joint return names
    both spouses; a statement may print the surname first).
    """
    on_document = name_tokens(doc.borrower)
    if not on_document:
        return "unknown"
    for name in borrower_names:
        wanted = name_tokens(name)
        if wanted and wanted <= on_document:
            return "matched"
    return "other"


def _year(text: str | None) -> int | None:
    found = re.search(r"\b(19|20)\d{2}\b", text or "")
    return int(found.group(0)) if found else None


# --- the items ------------------------------------------------------------------------------


class _Evaluation:
    def __init__(
        self,
        checklist: Checklist,
        messages: ChecklistsConfig,
        profile: Profile,
        docs: list[DocFacts],
    ):
        self.checklist, self.messages, self.profile = checklist, messages, profile
        self.docs = [d for d in docs if d.usable]

    def say(self, key: str, **values: object) -> str:
        return self.messages.message(key, **values)

    def borrower(self) -> str:
        return " and ".join(self.profile.borrower_names)

    def evaluate(self, item: ChecklistItem) -> ItemResult:
        of_type = [d for d in self.docs if d.doc_type == item.doc_type]
        owners = {d.id: owner_of(d, self.profile.borrower_names) for d in of_type}
        mine = [d for d in of_type if owners[d.id] == "matched"]
        unknown = [d for d in of_type if owners[d.id] == "unknown"]
        ids = [str(d.id) for d in mine + unknown]

        def result(status: Status, reason: str) -> ItemResult:
            return ItemResult(item.id, item.label, status, reason, ids)

        # 1. No usable document of the type for this borrower.
        if not mine and not unknown:
            return ItemResult(
                item.id,
                item.label,
                "missing",
                self.say("missing", noun=item.noun, borrower=self.borrower()),
            )
        # 2. Needs review: the owner is uncertain.
        if unknown:
            return result(
                "needs_review",
                self.say(
                    "needs_review",
                    noun=item.noun.capitalize(),
                    why="a document's owner could not be read",
                ),
            )

        status, reason = {
            "coverage_days": self._coverage_days,
            "coverage_months": self._coverage_months,
            "tax_years": self._tax_years,
            "recency": self._recency,
            "present": self._present,
        }[item.rule](item, mine)
        # A document that says it is incomplete makes a satisfied item partial (FSD rule 3).
        if status == "satisfied":
            problems = self._incomplete(mine)
            if problems:
                return result(
                    "partial",
                    self.say("incomplete_document", noun=item.noun.capitalize(), problem=problems),
                )
        elif status == "partial":
            problems = self._incomplete(mine)
            if problems:
                reason += "; " + self.say("incomplete_document", noun=item.noun, problem=problems)
        return result(status, reason)

    def _incomplete(self, docs: list[DocFacts]) -> str:
        found = {INCOMPLETE_FLAGS[c] for d in docs for c in d.open_flags if c in INCOMPLETE_FLAGS}
        return "; ".join(sorted(found))

    def _review(self, item: ChecklistItem, why: str) -> tuple[Status, str]:
        return "needs_review", self.say("needs_review", noun=item.noun.capitalize(), why=why)

    def _future(self, day: date | None) -> bool:
        return day is not None and day > self.profile.reference_date

    # coverage_days: pay stubs ----------------------------------------------------------------

    def _coverage_days(self, item: ChecklistItem, docs: list[DocFacts]) -> tuple[Status, str]:
        assert item.days is not None
        ranges = [(d.period_start, d.period_end) for d in docs if d.period_start and d.period_end]
        if len(ranges) < len(docs):
            return self._review(item, "the period of a document was not read")
        if any(self._future(end) for _, end in ranges):
            return self._review(item, "a document is dated after the reference date")
        span = longest(merge_ranges(ranges))
        found = span_days(span) if span else 0
        required = item.days.value
        text = self.say("coverage_days", found=found, required=required, noun=item.noun)
        return ("satisfied" if found >= required else "partial"), text

    # coverage_months: statements, per account ------------------------------------------------

    def _coverage_months(self, item: ChecklistItem, docs: list[DocFacts]) -> tuple[Status, str]:
        assert item.months is not None
        if any(not (d.period_start and d.period_end) for d in docs):
            return self._review(item, "the period of a document was not read")
        if any(self._future(d.period_end) for d in docs):
            return self._review(item, "a document is dated after the reference date")
        by_account: dict[str, list[tuple[date, date]]] = {}
        for doc in docs:
            account = doc.text("account_last4")
            if not account:
                return self._review(item, "the account of a document was not read")
            if doc.period_start and doc.period_end:
                by_account.setdefault(account, []).append((doc.period_start, doc.period_end))
        required = item.months.value
        parts: list[str] = []
        short = False
        for account, ranges in sorted(by_account.items()):
            span = longest(merge_ranges(ranges))
            found = months_covered(span) if span else 0
            short = short or found < required
            parts.append(
                self.say(
                    "coverage_months",
                    found=found,
                    required=required,
                    noun=item.noun,
                    account=account,
                )
            )
        return ("partial" if short else "satisfied"), "; ".join(parts)

    # tax_years: W-2s and returns -------------------------------------------------------------

    def _tax_years(self, item: ChecklistItem, docs: list[DocFacts]) -> tuple[Status, str]:
        assert item.year_offsets is not None
        years = {_year(d.text("tax_year")) for d in docs}
        if None in years:
            return self._review(item, "the tax year of a document was not read")
        if any(y is not None and y > self.profile.reference_date.year for y in years):
            return self._review(item, "a document is for a tax year after the reference year")
        required = sorted(self.profile.reference_date.year - o for o in item.year_offsets.value)
        have = [y for y in required if y in years]
        missing = [y for y in required if y not in years]
        if not missing:
            return "satisfied", self.say("satisfied", noun=item.noun.capitalize())
        return "partial", self.say(
            "tax_years",
            noun=item.noun.capitalize(),
            found=", ".join(map(str, have)) or "none",
            missing=", ".join(map(str, missing)),
        )

    # recency: a credit report ----------------------------------------------------------------

    def _recency(self, item: ChecklistItem, docs: list[DocFacts]) -> tuple[Status, str]:
        assert item.max_age_days is not None
        dates = [d.day("report_date") or d.period_end for d in docs]
        known = [day for day in dates if day is not None]
        if len(known) < len(dates):
            return self._review(item, "the date of the document was not read")
        latest = max(known)
        if self._future(latest):
            return self._review(item, "a document is dated after the reference date")
        age = (self.profile.reference_date - latest).days
        limit = item.max_age_days.value
        if age > limit:
            return "partial", self.say(
                "recency", noun=item.noun.capitalize(), days=age, limit=limit
            )
        return "satisfied", self.say("satisfied", noun=item.noun.capitalize())

    # present: an application or a letter -----------------------------------------------------

    def _present(self, item: ChecklistItem, docs: list[DocFacts]) -> tuple[Status, str]:
        if item.signed and not any(d.text("signed_date") for d in docs):
            return self._review(item, "no signature date was read")
        return "satisfied", self.say("present", noun=item.noun.capitalize())


def overall_of(items: list[ItemResult]) -> Overall:
    """FSD section 7: overrides count as satisfied."""
    counted = [i.status for i in items if i.override is None]
    if any(s in {"missing", "partial"} for s in counted):
        return "incomplete"
    if "needs_review" in counted:
        return "needs_review"
    return "complete"


def outstanding_of(items: list[ItemResult]) -> list[str]:
    """Plain text, one line for each item that still needs something, to copy."""
    return [
        f"{i.label}: {i.reason}" for i in items if i.override is None and i.status != "satisfied"
    ]


def evaluate(
    checklist: Checklist,
    messages: ChecklistsConfig,
    profile: Profile,
    docs: list[DocFacts],
) -> CompletenessOutcome:
    """Run a checklist over a case's documents."""
    run = _Evaluation(checklist, messages, profile, docs)
    items = [run.evaluate(item) for item in checklist.items]
    return CompletenessOutcome(items, overall_of(items), outstanding_of(items))

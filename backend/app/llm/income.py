"""Possible explanations for income flags, checked in code (Feature Design 2.5).

    outcome = await explain_income_flags(flags, evidence)
    for item in outcome.explanations:
        item.explanation.explanation, item.flags   # e.g. ["unverified figure"]

The model sees computed figures and short document facts only, never the
documents. Every number it writes must be one it was given; anything else is
marked "unverified figure". Explanations are labelled "possible — to be confirmed".
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field

from app.llm.checks import (
    DECISION_WORDING,
    UNVERIFIED_FIGURE,
    check_figures,
    decision_words,
    numbers_in,
)
from app.llm.gateway import Gateway, GatewayResult, get_gateway
from app.llm.tasks import clean_text
from app.prompts.schemas.income import (
    Explanation,
    IncomeEvidence,
    IncomeExplanations,
    IncomeFlag,
)


@dataclass(frozen=True)
class CheckedExplanation:
    explanation: Explanation
    flags: list[str] = field(default_factory=list)  # "unverified figure", "decision_wording"
    unverified_numbers: list[str] = field(default_factory=list)
    unknown_refs: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class ExplainOutcome:
    explanations: list[CheckedExplanation]
    call: GatewayResult[IncomeExplanations]
    # Explanations for flag codes that were not asked about; dropped and reported.
    unknown_flag_codes: list[str]


def format_flags(flags: Sequence[IncomeFlag]) -> str:
    rows = []
    for f in flags:
        compares = ", ".join(clean_text(r) for r in f.refs) or "-"
        rows.append(
            f"- code: {clean_text(f.code)} | {clean_text(f.message)} | compares: {compares}"
        )
    return "\n".join(rows)


def format_evidence(evidence: Sequence[IncomeEvidence]) -> str:
    return "\n".join(
        f"- {clean_text(e.ref)} | {clean_text(e.label)} | {clean_text(e.value)}" for e in evidence
    )


async def explain_income_flags(
    flags: Sequence[IncomeFlag],
    evidence: Sequence[IncomeEvidence],
    *,
    provider: str | None = None,
    gateway: Gateway | None = None,
) -> ExplainOutcome:
    """One income-explain@1 call for all flags of a run, then the figure and wording checks."""
    flag_text = format_flags(flags)
    evidence_text = format_evidence(evidence)
    call = await (gateway or get_gateway()).run(
        "income_explain",
        "income-explain@1",
        {"flags": flag_text, "evidence": evidence_text},
        IncomeExplanations,
        provider=provider,
    )

    # Any number in the inputs may be repeated: figures, years, box numbers, codes.
    allowed = numbers_in(flag_text, evidence_text)
    known_refs = {e.ref for e in evidence}
    known_codes = {f.code for f in flags}
    checked: list[CheckedExplanation] = []
    unknown_codes: list[str] = []
    for item in call.output.explanations:
        if item.flag_code not in known_codes:
            unknown_codes.append(item.flag_code)
            continue
        unverified = check_figures(item.explanation, allowed)
        unknown_refs = [r for r in item.evidence_refs if r not in known_refs]
        item_flags = []
        if unverified:
            item_flags.append(UNVERIFIED_FIGURE)
        if decision_words(item.explanation):
            item_flags.append(DECISION_WORDING)
        checked.append(CheckedExplanation(item, item_flags, unverified, unknown_refs))
    return ExplainOutcome(checked, call, list(dict.fromkeys(unknown_codes)))


@dataclass(frozen=True)
class StoredFlag:
    """A flag as the income analysis stored it: its code, message and working."""

    code: str
    message: str
    working: str | None = None


@dataclass(frozen=True)
class StoredCalculation:
    name: str
    formula: str
    working: str


async def explain_stored_flags(
    flags: Sequence[StoredFlag],
    calculations: Sequence[StoredCalculation],
    *,
    provider: str | None = None,
    gateway: Gateway | None = None,
) -> dict[str, dict[str, object]]:
    """Explanations for a stored income run, keyed by flag code, ready to store as JSON.

    Each calculation becomes an evidence item (ref = its name, value = its working), so every
    figure the model may repeat is one code computed. An explanation that uses decision wording
    is dropped (rule 3); one with a figure not in the inputs is kept and marked.
    """
    if not flags:
        return {}
    evidence = [IncomeEvidence(c.name, c.formula, c.working) for c in calculations]
    asked = [
        IncomeFlag(f.code, f.message + (f" ({f.working})" if f.working else ""), []) for f in flags
    ]
    outcome = await explain_income_flags(asked, evidence, provider=provider, gateway=gateway)
    stored: dict[str, dict[str, object]] = {}
    for item in outcome.explanations:
        if DECISION_WORDING in item.flags:
            continue
        e = item.explanation
        stored[e.flag_code] = {
            "text": e.explanation,
            "label": e.label,
            "evidence_refs": [r for r in e.evidence_refs if r not in item.unknown_refs],
            "suggested_documents": list(e.suggested_documents),
            "checks": list(item.flags),
            "unverified_numbers": list(item.unverified_numbers),
            "provider": outcome.call.provider,
            "model": outcome.call.model,
            "prompt_id": outcome.call.prompt_id,
        }
    return stored

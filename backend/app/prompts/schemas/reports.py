"""Output models for the Writer and Critic agents (Feature Design 6.5 and 8.5).

The Writer writes narrative only: the figures, the findings and the waterfall are built in code.
Everything it writes cites dossier refs, finding IDs or passage IDs, and code checks every number
and word afterwards (``app.agents.guardrails``).
"""

from __future__ import annotations

from typing import Literal

from app.prompts.schemas.fields import Schema

Priority = Literal["significant", "attention", "information"]


class Conflict(Schema):
    title: str
    detail: str
    evidence_refs: list[str]


class SuggestedCondition(Schema):
    text: str
    priority: Priority
    finding_ids: list[str]


class UnderwritingDraft(Schema):
    conflicts: list[Conflict]
    missing_information: list[str]
    potential_risks: list[str]
    conditions: list[SuggestedCondition]


class LmDraft(Schema):
    lender_view: str
    borrower_situation: str
    missing_information: list[str]
    compliance_points: list[str]
    items_for_human_review: list[str]


class CriticFix(Schema):
    where: str  # the section and item, e.g. "conditions[2]" or "lender_view"
    problem: str
    fix: str


class CriticVerdict(Schema):
    verdict: Literal["pass", "fix"]
    fixes: list[CriticFix]

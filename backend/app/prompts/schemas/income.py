"""Inputs and output model for income-explain@1 (Feature Design 2.5).

The model sees computed flags and figures only, never the documents. It proposes
possible explanations, each labelled "possible — to be confirmed", citing the
input items it relies on, and lists documents that would settle the question.
Code then checks every figure in an explanation against the inputs.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from app.prompts.schemas.fields import Schema

POSSIBLE_LABEL = "possible — to be confirmed"


@dataclass(frozen=True)
class IncomeEvidence:
    """One input item the model may cite: a computed figure or a fact from a document.

    ``ref`` is a stable ID the caller chooses (``w2_2025.box12``); ``value`` is a
    string exactly as computed or printed, never a float.
    """

    ref: str
    label: str
    value: str


@dataclass(frozen=True)
class IncomeFlag:
    """A discrepancy found in code, with the refs of the items it compares."""

    code: str
    message: str
    refs: list[str] = field(default_factory=list)


class Explanation(Schema):
    flag_code: str
    explanation: str
    label: Literal["possible — to be confirmed"]
    evidence_refs: list[str]
    suggested_documents: list[str]


class IncomeExplanations(Schema):
    explanations: list[Explanation]

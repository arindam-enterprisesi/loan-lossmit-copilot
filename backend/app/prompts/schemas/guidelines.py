"""Output model for answer@1, the guideline assistant's cited answer (Feature Design 5.5).

The model answers only from the numbered passages it is given. Every sentence cites at least
one passage by its marker; a quotation must be copied exactly from a cited passage. Code checks
all of it afterwards (``app.rag.answer``) and removes any sentence that fails.
"""

from __future__ import annotations

from typing import Literal

from app.prompts.schemas.fields import Schema


class AnswerSentence(Schema):
    text: str
    citations: list[int]
    quote: str | None


class Comparison(Schema):
    topic: str
    markers: list[int]


class GuidelineAnswerResult(Schema):
    status: Literal["answered", "no_support"]
    sentences: list[AnswerSentence]
    comparison: Comparison | None
    facts_to_check: list[str]

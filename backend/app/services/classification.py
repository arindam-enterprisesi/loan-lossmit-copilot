"""Classify a document from its first pages, and decide whether its type can be applied.

``Classifier`` is the seam to the model. ``LlmClassifier`` calls Arindam's
``app.llm.tasks.classify`` (content only, never the file name); ``FakeClassifier``
(``app.services.fake_reader``) is the rule-based stand-in for offline work and tests.
``decide_type`` is plain code and follows FSD 4.4: auto-detect applies a type only when the model
is certain, and a picked type that a certain model disagrees with holds extraction until a person
chooses.
"""

from __future__ import annotations

import importlib
import importlib.util
import logging
from collections.abc import Sequence
from dataclasses import dataclass
from types import ModuleType
from typing import Any, Literal, Protocol

from app.services.doc_lines import DocLine
from app.settings import get_settings

logger = logging.getLogger(__name__)


class PipelineUnavailableError(Exception):
    """A reader the pipeline needs cannot be used (a real task exists but is not wired)."""


@dataclass(frozen=True)
class Classification:
    doc_type: str
    certainty: str  # high | medium | low
    justification_line_ids: list[str]
    unknown_line_ids: list[str]  # cited lines that were not in the input (the caller flags these)
    provider: str
    model: str
    prompt_id: str | None = None


class Classifier(Protocol):
    async def classify(self, lines: Sequence[DocLine]) -> Classification: ...


def llm_tasks() -> ModuleType | None:
    """Arindam's ``app.llm.tasks`` module, or None while it is not in this tree.

    Only a missing module is treated as "not there": any other import error is raised, so a broken
    task is never hidden behind the fake.
    """
    if importlib.util.find_spec("app.llm.tasks") is None:
        return None
    return importlib.import_module("app.llm.tasks")


class LlmClassifier:
    """The real classify task (the only caller of it in the pipeline)."""

    def __init__(self, *, gateway: Any | None = None, provider: str | None = None) -> None:
        self._gateway = gateway
        self._provider = provider

    async def classify(self, lines: Sequence[DocLine]) -> Classification:
        tasks = llm_tasks()
        if tasks is None:
            raise PipelineUnavailableError("app.llm.tasks is not available")
        outcome = await tasks.classify(
            [tasks.DocumentLine(ln.page, ln.line, ln.text) for ln in lines],
            provider=self._provider,
            gateway=self._gateway,
        )
        result, call = outcome.result, outcome.call
        return Classification(
            doc_type=str(getattr(result.doc_type, "value", result.doc_type)),
            certainty=result.certainty,
            justification_line_ids=list(result.justification_line_ids),
            unknown_line_ids=list(outcome.unknown_line_ids),
            provider=call.provider,
            model=call.model,
            prompt_id=call.prompt_id,
        )


def get_classifier(mode: str | None = None) -> Classifier:
    """The classifier for this process: real when the task exists, else the fake (and say so)."""
    from app.services.fake_reader import FakeClassifier

    mode = mode or get_settings().pipeline_llm
    if mode != "fake":
        tasks = llm_tasks()
        if tasks is not None and hasattr(tasks, "classify"):
            logger.info("classify: using the real task (app.llm.tasks.classify)")
            return LlmClassifier()
    logger.warning("classify: using the rule-based fake reader (PIPELINE_LLM=%s)", mode)
    return FakeClassifier()


# --- the type decision (FSD 4.4) -------------------------------------------------------------


@dataclass(frozen=True)
class TypeDecision:
    doc_type: str | None  # None: a person must choose
    source: Literal["ai", "user"]
    needs_choice: bool
    flag: Literal["DI-W501", "DI-W502"] | None
    predicted: str
    selected: str | None  # the type the user picked at upload, if any


def decide_type(declared: str | None, result: Classification) -> TypeDecision:
    """Apply the type when it is certain; otherwise ask (DI-W501) or flag the disagreement."""
    certain = result.certainty == "high" and result.doc_type != "unrecognized"
    if declared is None:  # auto-detect
        if certain:
            return TypeDecision(result.doc_type, "ai", False, None, result.doc_type, None)
        return TypeDecision(None, "ai", True, "DI-W501", result.doc_type, None)
    if result.doc_type == declared:
        return TypeDecision(declared, "user", False, None, result.doc_type, declared)
    if certain:  # a type the user picked, and a certain model disagrees: hold extraction
        return TypeDecision(None, "user", True, "DI-W502", result.doc_type, declared)
    flagged: Literal["DI-W502"] | None = "DI-W502" if result.doc_type != "unrecognized" else None
    return TypeDecision(declared, "user", False, flagged, result.doc_type, declared)

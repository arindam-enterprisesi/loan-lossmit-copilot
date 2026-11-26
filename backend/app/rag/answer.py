"""The cited answer (Feature Design 5.4 steps 4 to 8): retrieve, call answer@1, check in code.

    answer = await ask("How is overtime income evaluated?", "all")

With no passage above the threshold the answer is "no supporting passage found" and no model is
called. Otherwise the model writes short sentences, each citing passages by marker, and code
then removes every sentence that

* cites nothing, or a marker that was not retrieved;
* quotes text that is not an exact piece of a passage it cites, or quotes more than allowed;
* repeats a number (a period, a date part, an amount) that no passage it cites contains;
* uses decision wording (rule 3).

The number of removed sentences is part of the answer, so the screen can say so. If every
sentence is removed, the answer becomes "no supporting passage found".
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from app.llm.checks import check_figures, decision_words, normalise, numbers_in
from app.llm.gateway import Gateway, get_gateway
from app.llm.tasks import clean_text
from app.prompts.schemas.guidelines import GuidelineAnswerResult
from app.rag.store import Hit, RagStore, get_rag_store

NO_SUPPORT = "no supporting passage found"
TASK = "guideline_answer"
PROMPT_ID = "answer@1"


@dataclass
class CheckedAnswer:
    """What the endpoint returns (``frontend/src/lib/guidelines-types.ts`` GuidelineAnswer)."""

    id: str
    question: str
    source_set: str
    case_id: str | None
    asked_at: str
    status: str  # "answered" | "no_support"
    sentences: list[dict[str, Any]]
    citations: list[dict[str, Any]]
    passages: list[dict[str, Any]]
    comparison: dict[str, Any] | None
    facts_to_check: list[str]
    notice: str | None
    removed_sentences: int
    # Not shown to the reader; kept for the audit record and the evaluation.
    retrieved: list[dict[str, Any]] = field(default_factory=list)
    removed: list[dict[str, Any]] = field(default_factory=list)
    model: dict[str, Any] | None = None

    def public(self) -> dict[str, Any]:
        out = dict(vars(self))
        for key in ("retrieved", "removed", "model"):
            out.pop(key)
        return out


def format_passages(hits: Sequence[Hit]) -> str:
    blocks = []
    for marker, hit in enumerate(hits, start=1):
        s = hit.source
        blocks.append(
            f"[{marker}] {clean_text(s.title)} | section {clean_text(hit.passage.section)}: "
            f"{clean_text(hit.passage.heading)} | {s.label}"
            + (f" | version {clean_text(s.version)}" if s.version else "")
            + f"\n{clean_text(hit.passage.text)}"
        )
    return "\n\n".join(blocks)


def passage_out(store: RagStore, hit: Hit) -> dict[str, Any]:
    s = hit.source
    return {
        "id": hit.passage.id,
        "source_id": s.id,
        "source_title": s.title,
        "heading": f"{hit.passage.section} {hit.passage.heading}",
        "text": hit.passage.text,
        "label": s.label,
        "page": hit.passage.page,
        "version": s.version,
        "notice": s.notice,
    }


def _check_sentence(
    sentence: Any, hits: Sequence[Hit], max_quote_chars: int
) -> tuple[list[int], str | None]:
    """The sentence's valid markers, or the reason it is removed."""
    markers = list(dict.fromkeys(sentence.citations))
    if not markers:
        return [], "no citation"
    if any(m < 1 or m > len(hits) for m in markers):
        return [], "cites a passage that was not retrieved"
    cited = [hits[m - 1].passage for m in markers]
    if sentence.quote is not None and sentence.quote.strip():
        quote = normalise(sentence.quote)
        if len(sentence.quote) > max_quote_chars:
            return [], "quotation too long"
        if not any(quote in normalise(p.text) for p in cited):
            return [], "quotation is not in the cited passage"
    unverified = check_figures(sentence.text, numbers_in(*(f"{p.section} {p.text}" for p in cited)))
    if unverified:
        return [], "a figure is not in the cited passages: " + ", ".join(unverified)
    if decision_words(sentence.text):
        return [], "decision wording"
    return markers, None


async def ask(
    question: str,
    source_set: str = "all",
    *,
    case_id: str | None = None,
    case_facts: Sequence[str] = (),
    store: RagStore | None = None,
    gateway: Gateway | None = None,
    provider: str | None = None,
) -> CheckedAnswer:
    store = store or get_rag_store()
    cfg = store.config
    hits = store.search(question, source_set)
    answer = CheckedAnswer(
        id=str(uuid.uuid4()),
        question=question,
        source_set=source_set,
        case_id=case_id,
        asked_at=datetime.now(UTC).isoformat(),
        status="no_support",
        sentences=[],
        citations=[],
        passages=[],
        comparison=None,
        facts_to_check=[],
        notice=None,
        removed_sentences=0,
        retrieved=[
            {"passage_id": h.passage.id, "score": round(h.score, 4), "direct": h.direct}
            for h in hits
        ],
    )
    if source_set == "regulation_x":
        answer.notice = cfg.regulation_notice
    if not hits:
        return answer  # Feature Design 5.5: no passage, no model call

    facts = "\n".join(f"- {clean_text(f)}" for f in case_facts) or "(no case attached)"
    call = await (gateway or get_gateway()).run(
        TASK,
        PROMPT_ID,
        {
            "question": clean_text(question),
            "passages": format_passages(hits),
            "case_facts": facts,
            "max_quote_chars": cfg.max_quote_chars,
        },
        GuidelineAnswerResult,
        provider=provider,
    )
    out = call.output
    answer.model = {
        "provider": call.provider,
        "model": call.model,
        "prompt_id": call.prompt_id,
        "input_tokens": call.input_tokens,
        "output_tokens": call.output_tokens,
    }

    used: list[int] = []
    for sentence in out.sentences if out.status == "answered" else []:
        markers, reason = _check_sentence(sentence, hits, cfg.max_quote_chars)
        if reason:
            answer.removed.append({"text": sentence.text, "reason": reason})
            continue
        answer.sentences.append({"text": sentence.text, "citations": markers})
        used.extend(m for m in markers if m not in used)
    answer.removed_sentences = len(answer.removed)
    if not answer.sentences:
        return answer

    # Markers are renumbered 1..n in the order they are first cited, and only cited passages
    # are returned, so every marker on screen opens a passage.
    renumber = {old: new for new, old in enumerate(used, start=1)}
    for s in answer.sentences:
        s["citations"] = [renumber[m] for m in s["citations"]]
    cited_hits = [hits[old - 1] for old in used]
    answer.status = "answered"
    answer.citations = [
        {"marker": renumber[old], "passage_id": hits[old - 1].passage.id} for old in used
    ]
    answer.passages = [passage_out(store, h) for h in cited_hits]
    if out.comparison is not None:
        markers = [renumber[m] for m in out.comparison.markers if m in renumber]
        sources = {cited_hits[m - 1].source.id for m in markers}
        if len(markers) >= 2 and len(sources) >= 2:
            answer.comparison = {"topic": out.comparison.topic, "markers": markers}
    if case_facts:
        answer.facts_to_check = [f for f in out.facts_to_check if not decision_words(f)]
    if any(h.source.kind == "regulation" for h in cited_hits):
        answer.notice = cfg.regulation_notice
    return answer

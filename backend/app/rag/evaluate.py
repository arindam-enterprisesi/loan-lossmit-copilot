"""Evaluate the guideline assistant on a fixed question set (Feature Design 5.8).

    uv run python -m app.rag.evaluate                 # retrieval only: no model call, no key
    uv run python -m app.rag.evaluate --answers       # also answers each question (provider calls)
    uv run python -m app.rag.evaluate --answers --provider bedrock

Retrieval hit rate: the share of answerable questions whose expected passage is retrieved.
No-support accuracy: the share of unanswerable questions that retrieve nothing.
Citation validity (with ``--answers``): the share of returned sentences whose citations survived
the checks, and the share of answers that cite an expected passage.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from dataclasses import dataclass

from app.rag.store import RagStore, get_rag_store


@dataclass(frozen=True)
class EvalQuestion:
    question: str
    source_set: str
    expected: tuple[str, ...]  # any of these passages counts as a hit; () = no support expected


QUESTIONS: tuple[EvalQuestion, ...] = (
    EvalQuestion(
        "How is overtime income evaluated?",
        "all",
        ("fnma-sg.B3-3.1-01.variable", "fhlmc-guide.5303.1"),
    ),
    EvalQuestion(
        "What does the lender overlay say about overtime?", "guidelines", ("lender-overlay.LO-1",)
    ),
    EvalQuestion(
        "How recent must a pay stub be?", "guidelines", ("fnma-sg.B3-3.1-02", "fhlmc-guide.5302.2")
    ),
    EvalQuestion(
        "Which large deposits need a documented source?",
        "guidelines",
        ("fnma-sg.B3-4.2-02", "fhlmc-guide.5501.3", "lender-overlay.LO-3"),
    ),
    EvalQuestion(
        "What happens if a statement page is missing?",
        "guidelines",
        ("fnma-sg.B3-4.2-01", "fhlmc-guide.5501.3"),
    ),
    EvalQuestion(
        "How is the representative credit score chosen?",
        "guidelines",
        ("fnma-sg.B3-5.1-02", "fhlmc-guide.5203.1"),
    ),
    EvalQuestion(
        "Which monthly debts count in the debt-to-income ratio?",
        "guidelines",
        ("fnma-sg.B3-6-05", "fhlmc-guide.5401.2", "fnma-sg.B3-6-02"),
    ),
    EvalQuestion("Is a gift letter needed for gift funds?", "guidelines", ("fnma-sg.B3-4.3-04",)),
    EvalQuestion(
        "What is the lender's debt-to-income review level?", "guidelines", ("lender-overlay.LO-2",)
    ),
    EvalQuestion(
        "The application is missing a bank statement. What must the servicer do?",
        "regulation_x",
        ("reg-x-1024-41.b",),
    ),
    EvalQuestion(
        "How long does a servicer have to evaluate a complete application?",
        "regulation_x",
        ("reg-x-1024-41.c",),
    ),
    EvalQuestion(
        "How many days delinquent before a foreclosure referral?",
        "regulation_x",
        ("reg-x-1024-41.f",),
    ),
    EvalQuestion("What does 1024.41(b) require?", "all", ("reg-x-1024-41.b",)),
    EvalQuestion(
        "When is a loan modification considered under Sample Investor A?",
        "guidelines",
        (
            "sample-investor-a-v1.loan-modification.1",
            "sample-investor-a-v1.loan-modification.2",
            "sample-investor-a-v1.loan-modification.3",
        ),
    ),
    EvalQuestion("What are the requirements for jumbo loans?", "all", ()),
    EvalQuestion("What is the state usury limit in Ohio?", "all", ()),
)


def retrieval_report(store: RagStore) -> dict[str, object]:
    rows = []
    for q in QUESTIONS:
        found = [h.passage.id for h in store.search(q.question, q.source_set)]
        ok = (not found) if not q.expected else bool(set(found) & set(q.expected))
        rows.append(
            {"question": q.question, "found": found, "expected": list(q.expected), "ok": ok}
        )
    answerable = [r for r, q in zip(rows, QUESTIONS, strict=True) if q.expected]
    unanswerable = [r for r, q in zip(rows, QUESTIONS, strict=True) if not q.expected]
    return {
        "questions": len(rows),
        "retrieval_hit_rate": f"{sum(bool(r['ok']) for r in answerable)}/{len(answerable)}",
        "no_support_accuracy": f"{sum(bool(r['ok']) for r in unanswerable)}/{len(unanswerable)}",
        "rows": rows,
    }


async def answer_report(store: RagStore, provider: str | None) -> dict[str, object]:
    from app.rag.answer import ask

    rows = []
    kept = removed = cites_expected = answered = 0
    for q in QUESTIONS:
        a = await ask(q.question, q.source_set, store=store, provider=provider)
        cited = {c["passage_id"] for c in a.citations}
        kept += len(a.sentences)
        removed += a.removed_sentences
        if q.expected and a.status == "answered":
            answered += 1
            cites_expected += bool(cited & set(q.expected))
        rows.append(
            {
                "question": q.question,
                "status": a.status,
                "cited": sorted(cited),
                "sentences": len(a.sentences),
                "removed": a.removed,
                "model": a.model,
            }
        )
    return {
        "citation_validity": f"{kept}/{kept + removed} sentences kept",
        "answers_citing_an_expected_passage": f"{cites_expected}/{answered}",
        "rows": rows,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--answers", action="store_true")
    parser.add_argument("--provider", default=None)
    args = parser.parse_args(argv)
    store = get_rag_store()
    report: dict[str, object] = {"retrieval": retrieval_report(store)}
    if args.answers:
        report["answers"] = asyncio.run(answer_report(store, args.provider))
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())

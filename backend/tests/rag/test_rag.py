"""The guideline assistant: loading, retrieval and the code checks on answers (Feature Design 5)."""

import json
from pathlib import Path
from typing import Any

import pytest

from app.llm.gateway import Gateway
from app.llm.types import AdapterResponse
from app.rag.answer import ask
from app.rag.sources import SourceError, load_all, parse_source
from app.rag.store import build_store
from tests.llm.fakes import FakeAdapter, fake_config

STORE = build_store()


def ids(question: str, source_set: str = "all") -> list[str]:
    return [h.passage.id for h in STORE.search(question, source_set)]


# ---------- loading ----------


def test_every_source_is_loaded_and_labelled() -> None:
    sources = {s.id: s for s in STORE.source_info()}
    assert set(sources) == {
        "fnma-sg",
        "fhlmc-guide",
        "lender-overlay",
        "reg-x-1024-41",
        "sample-investor-a-v1",
    }
    assert {s.label for s in sources.values()} == {"illustrative"}
    assert sources["reg-x-1024-41"].notice == "Not legal advice; confirm with your compliance team."


def test_feature_8_passage_ids_still_resolve() -> None:
    """The rules engine cites the seeded Sample Investor A IDs; Regulation X (b) keeps its ID."""
    seeded = json.loads(Path("app/db/demo/guideline_passages.json").read_text(encoding="utf-8"))
    for p in seeded["passages"]:
        assert STORE.passage(p["id"]) is not None, p["id"]
    assert "missing documents" in STORE.passage("reg-x-1024-41.b").text  # the file replaced it


def test_a_source_without_front_matter_or_sections_is_refused() -> None:
    with pytest.raises(SourceError, match="front-matter"):
        parse_source("## a | b\ntext")
    with pytest.raises(SourceError, match="passages"):
        parse_source("---\nid: x\ntitle: X\nkind: agency_guide\nlabel: illustrative\n---\nbody")
    with pytest.raises(SourceError, match="label"):
        parse_source("---\nid: x\ntitle: X\nkind: agency_guide\nlabel: maybe\n---\n## a | b\nt")


def test_a_missing_directory_still_loads_the_seeded_passages(tmp_path: Path) -> None:
    sources, passages = load_all(tmp_path / "nowhere")
    assert "sample-investor-a-v1" in sources
    assert "reg-x-1024-41.b" in passages


# ---------- retrieval (Feature Design 5.8 examples) ----------


def test_overtime_finds_fannie_mae_and_freddie_mac() -> None:
    found = ids("How is overtime income evaluated?")
    assert {"fnma-sg.B3-3.1-01.variable", "fhlmc-guide.5303.1"} <= set(found[:3])


def test_overlay_question_finds_the_overlay() -> None:
    assert ids("What does the lender overlay say about overtime?")[0] == "lender-overlay.LO-1"


def test_jumbo_loans_find_nothing() -> None:
    assert ids("What are the requirements for jumbo loans?") == []


def test_missing_document_in_an_application_cites_1024_41_b() -> None:
    q = "The application is missing a bank statement. What must the servicer do?"
    assert ids(q, "regulation_x")[0] == "reg-x-1024-41.b"


def test_a_named_section_is_looked_up_directly() -> None:
    hits = STORE.search("What does 1024.41(b) require?")
    assert hits[0].passage.id == "reg-x-1024-41.b" and hits[0].direct
    assert ids("Show me B3-4.2-02")[0] == "fnma-sg.B3-4.2-02"


def test_source_sets_limit_the_search() -> None:
    assert all(i.startswith("reg-x") for i in ids("servicer application", "regulation_x"))
    assert not any(i.startswith("reg-x") for i in ids("servicer application", "guidelines"))


# ---------- the answer and its checks ----------


def reply(body: dict[str, Any]) -> AdapterResponse:
    return AdapterResponse(text=json.dumps(body), input_tokens=900, output_tokens=200)


def s(text: str, *markers: int, quote: str | None = None) -> dict[str, Any]:
    return {"text": text, "citations": list(markers), "quote": quote}


async def run(question: str, body: dict[str, Any], **kwargs: Any) -> Any:
    adapter = FakeAdapter([reply(body)])
    answer = await ask(
        question, gateway=Gateway({"fake": adapter}, fake_config()), store=STORE, **kwargs
    )
    return answer, adapter


OVERTIME = "How is overtime income evaluated?"


async def test_overtime_answer_with_side_by_side_sources() -> None:
    hits = STORE.search(OVERTIME)
    fnma = 1 + [h.passage.id for h in hits].index("fnma-sg.B3-3.1-01.variable")
    fhlmc = 1 + [h.passage.id for h in hits].index("fhlmc-guide.5303.1")
    answer, adapter = await run(
        OVERTIME,
        {
            "status": "answered",
            "sentences": [
                s("Fannie Mae expects at least two years of overtime history.", fnma),
                s(
                    "Freddie Mac accepts at least 12 months with positive factors.",
                    fhlmc,
                    quote="A history of at least 12 months may be acceptable",
                ),
            ],
            "comparison": {"topic": "Overtime history", "markers": [fnma, fhlmc]},
            "facts_to_check": ["ignored without a case"],
        },
    )
    assert answer.status == "answered"
    assert [c["passage_id"] for c in answer.citations] == [
        "fnma-sg.B3-3.1-01.variable",
        "fhlmc-guide.5303.1",
    ]
    assert [x["citations"] for x in answer.sentences] == [[1], [2]]
    assert answer.comparison == {"topic": "Overtime history", "markers": [1, 2]}
    assert answer.facts_to_check == []
    assert answer.removed_sentences == 0
    assert answer.notice is None
    user = adapter.requests[0].messages[0].content
    assert "| section 5303.1: Overtime and bonus income | illustrative" in user
    assert "(no case attached)" in user
    assert "data" in (adapter.requests[0].system or "")


async def test_failing_sentences_are_removed_and_counted() -> None:
    answer, _ = await run(
        OVERTIME,
        {
            "status": "answered",
            "sentences": [
                s("No citation here."),
                s("Cites a passage that was not retrieved.", 42),
                s("Made-up quote.", 1, quote="overtime is always fine"),
                s("Overtime needs 36 months of history.", 1),  # 36 is in no cited passage
                s("The borrower is eligible.", 1),
                s("Overtime may be used with a history of receipt.", 1),
            ],
            "comparison": None,
            "facts_to_check": [],
        },
    )
    assert answer.removed_sentences == 5
    assert [r["reason"] for r in answer.removed] == [
        "no citation",
        "cites a passage that was not retrieved",
        "quotation is not in the cited passage",
        "a figure is not in the cited passages: 36",
        "decision wording",
    ]
    assert len(answer.sentences) == 1 and answer.status == "answered"


async def test_everything_removed_means_no_support() -> None:
    answer, _ = await run(
        OVERTIME,
        {
            "status": "answered",
            "sentences": [s("Uncited.")],
            "comparison": None,
            "facts_to_check": [],
        },
    )
    assert answer.status == "no_support" and answer.removed_sentences == 1


async def test_no_passage_means_no_model_call() -> None:
    adapter = FakeAdapter([])
    answer = await ask(
        "What are the requirements for jumbo loans?",
        gateway=Gateway({"fake": adapter}, fake_config()),
        store=STORE,
    )
    assert answer.status == "no_support"
    assert adapter.requests == []


async def test_regulation_answer_carries_the_notice_and_facts_to_check() -> None:
    q = "The application is missing a bank statement. What must the servicer do?"
    answer, adapter = await run(
        q,
        {
            "status": "answered",
            "sentences": [
                s(
                    "Within 5 days after receipt the servicer notifies the borrower whether the "
                    "application is complete or incomplete.",
                    1,
                ),
            ],
            "comparison": None,
            "facts_to_check": [
                "The date the application was received",
                "Whether the borrower qualifies",  # decision wording: dropped
            ],
        },
        source_set="regulation_x",
        case_facts=["Missing: the August 2026 bank statement"],
    )
    assert answer.citations[0]["passage_id"] == "reg-x-1024-41.b"
    assert answer.notice == "Not legal advice; confirm with your compliance team."
    assert answer.facts_to_check == ["The date the application was received"]
    assert "- Missing: the August 2026 bank statement" in adapter.requests[0].messages[0].content


def test_the_evaluation_set_retrieves_every_expected_passage() -> None:
    """Feature Design 5.8: retrieval hit rate on the fixed question set (no model call)."""
    from app.rag.evaluate import QUESTIONS, retrieval_report

    report = retrieval_report(STORE)
    assert len(QUESTIONS) >= 15
    answerable = sum(1 for q in QUESTIONS if q.expected)
    assert report["retrieval_hit_rate"] == f"{answerable}/{answerable}"
    unanswerable = len(QUESTIONS) - answerable
    assert report["no_support_accuracy"] == f"{unanswerable}/{unanswerable}"

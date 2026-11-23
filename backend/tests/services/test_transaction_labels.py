"""The transaction labellers: the fake matches the generated scenarios, the real one wraps the task.

Nothing here calls a model. ``LlmLabeller`` runs behind Arindam's gateway with a fake provider, the
same way ``test_llm_extractor.py`` does it.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from app.llm.gateway import Gateway
from app.llm.tasks import TransactionInput
from app.llm.types import AdapterResponse
from app.prompts.schemas.transactions import TransactionCategory
from app.services.transaction_labels import FakeLabeller, LlmLabeller
from tests.llm.fakes import FakeAdapter, fake_config

SCENARIOS = Path(__file__).resolve().parents[3] / "data" / "synthetic" / "scenarios"


def scenario_lines(name: str) -> list[dict[str, Any]]:
    data = json.loads((SCENARIOS / f"{name}.json").read_text(encoding="utf-8"))
    return [
        t
        for doc in data["documents"]
        if doc["type"] == "bank_statement"
        for t in doc["facts"]["transactions"]
    ]


def inputs(lines: list[dict[str, Any]]) -> list[TransactionInput]:
    return [
        TransactionInput(f"p1-L{n}", t["date"], t["description"], t["amount"])
        for n, t in enumerate(lines, start=10)
    ]


@pytest.mark.parametrize("name", ["daniel_reyes", "angela_whitfield"])
async def test_the_fake_labeller_gives_every_generated_line_its_scenario_category(
    name: str,
) -> None:
    lines = scenario_lines(name)

    labels = await FakeLabeller().label(inputs(lines), borrower_names=[], employer_names=[])

    got = [(t["description"], label.category.value) for t, label in zip(lines, labels, strict=True)]
    want = [(t["description"], t["category"]) for t in lines]
    assert got == want
    assert [label.line_id for label in labels] == [f"p1-L{n}" for n in range(10, 10 + len(lines))]


async def test_the_fake_labeller_names_the_payee_of_the_debts_and_transfers() -> None:
    lines = scenario_lines("daniel_reyes") + scenario_lines("angela_whitfield")
    labels = await FakeLabeller().label(inputs(lines), borrower_names=[], employer_names=[])

    names = {t["description"]: label.counterparty for t, label in zip(lines, labels, strict=True)}

    assert names["ZELLE FROM PATRICIA OWENS REF 8841"] == "Patricia Owens"
    assert names["ZELLE TO R WHITFIELD"] == "R Whitfield"
    assert names["LAKESHORE AUTO FINANCE"] == "Lakeshore Auto Finance"
    assert names["BRIGHTPATH STUDENT LOAN"] == "Brightpath Student Loan"
    assert names["OAKMONT APARTMENTS RENT"] == "Oakmont Apartments"
    assert names["ALDI 55021"] == "Aldi"


async def test_the_fake_labeller_does_not_guess_beyond_its_keywords() -> None:
    odd = [
        TransactionInput("p1-L1", "2026-09-01", "ACME WIDGETS 99", "-12.00"),
        TransactionInput("p1-L2", "2026-09-02", "MYSTERY CREDIT", "50.00"),
        TransactionInput("p1-L3", "2026-09-03", "OVERDRAFT FEE", "-35.00"),
    ]

    labels = await FakeLabeller().label(odd, borrower_names=[], employer_names=[])

    assert [label.category for label in labels] == [
        TransactionCategory.OTHER,
        TransactionCategory.OTHER_INCOME_DEPOSIT,
        TransactionCategory.OVERDRAFT_OR_RETURNED_ITEM_FEE,
    ]
    assert not any(label.needs_review for label in labels)


# --- the real labeller, with a fake provider ---------------------------------------------------


def reply(*labels: dict[str, Any]) -> AdapterResponse:
    return AdapterResponse(text=json.dumps({"labels": list(labels)}))


async def test_the_llm_labeller_returns_the_tasks_labels_in_input_order() -> None:
    lines = inputs(scenario_lines("daniel_reyes")[:2])
    adapter = FakeAdapter(
        [
            reply(
                {"line_id": lines[1].line_id, "category": "everyday spending", "counterparty": "B"},
                {"line_id": lines[0].line_id, "category": "housing payment", "counterparty": "A"},
            )
        ]
    )
    labeller = LlmLabeller(gateway=Gateway({"fake": adapter}, fake_config()))

    labels = await labeller.label(lines, borrower_names=["Daniel Reyes"], employer_names=[])

    assert [(x.line_id, x.category.value) for x in labels] == [
        (lines[0].line_id, "housing payment"),
        (lines[1].line_id, "everyday spending"),
    ]
    assert len(adapter.requests) == 1


async def test_the_llm_labeller_with_no_lines_makes_no_call() -> None:
    adapter = FakeAdapter([])
    labeller = LlmLabeller(gateway=Gateway({"fake": adapter}, fake_config()))

    assert await labeller.label([], borrower_names=[], employer_names=[]) == []
    assert adapter.requests == []

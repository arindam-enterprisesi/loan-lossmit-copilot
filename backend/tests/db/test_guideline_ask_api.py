"""POST /guidelines/ask and feedback (Feature Design 5.7), with a fake model behind the gateway."""

from __future__ import annotations

import json
from collections.abc import Iterator
from typing import Any

import httpx
import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.enums import Role
from app.db.models import AuditEvent
from app.db.seed import case_id, seed
from app.llm import gateway as gateway_module
from app.llm.gateway import Gateway
from app.llm.types import AdapterResponse
from tests.db.conftest import auth_headers
from tests.llm.fakes import FakeAdapter, fake_config

DANIEL = case_id("Daniel Reyes — purchase")
ANGELA = case_id("Angela Whitfield — hardship")


@pytest.fixture(autouse=True)
async def seeded(session: AsyncSession) -> None:
    await seed(session, "demo-pass")


@pytest.fixture
def model(monkeypatch: pytest.MonkeyPatch) -> Iterator[FakeAdapter]:
    adapter = FakeAdapter([])
    monkeypatch.setattr(
        gateway_module, "_default_gateway", Gateway({"fake": adapter}, fake_config())
    )
    yield adapter


def answer_body(*sentences: dict[str, Any], facts: list[str] | None = None) -> AdapterResponse:
    body = {
        "status": "answered",
        "sentences": list(sentences),
        "comparison": None,
        "facts_to_check": facts or [],
    }
    return AdapterResponse(text=json.dumps(body), input_tokens=500, output_tokens=100)


async def test_a_cited_answer_and_its_audit_record(
    client: httpx.AsyncClient, session: AsyncSession, model: FakeAdapter
) -> None:
    model.responses.append(
        answer_body(
            {
                "text": "Overtime may be used with a history of receipt.",
                "citations": [1],
                "quote": None,
            }
        )
    )
    response = await client.post(
        "/api/v1/guidelines/ask",
        json={"question": "How is overtime income evaluated?", "source_set": "all"},
        headers=auth_headers(Role.UNDERWRITER),
    )

    assert response.status_code == 200, response.text
    answer = response.json()
    assert answer["status"] == "answered"
    assert answer["citations"][0]["marker"] == 1
    assert answer["passages"][0]["label"] == "illustrative"
    assert answer["removed_sentences"] == 0
    event = await session.scalar(
        sa.select(AuditEvent).where(AuditEvent.action == "guideline.asked")
    )
    assert event is not None and event.after["status"] == "answered"
    assert event.after["retrieved"]  # the passages and scores are kept (Feature Design 5.6)

    feedback = await client.post(
        f"/api/v1/guidelines/answers/{answer['id']}/feedback",
        json={"rating": "helpful"},
        headers=auth_headers(Role.UNDERWRITER),
    )
    assert feedback.status_code == 204
    unknown = await client.post(
        "/api/v1/guidelines/answers/00000000-0000-0000-0000-000000000000/feedback",
        json={"rating": "helpful"},
        headers=auth_headers(Role.UNDERWRITER),
    )
    assert unknown.status_code == 404


async def test_no_supporting_passage_calls_no_model(
    client: httpx.AsyncClient, model: FakeAdapter
) -> None:
    response = await client.post(
        "/api/v1/guidelines/ask",
        json={"question": "What are the requirements for jumbo loans?"},
        headers=auth_headers(Role.LM_SPECIALIST),
    )
    assert response.status_code == 200
    assert response.json()["status"] == "no_support"
    assert model.requests == []


async def test_case_aware_question_sends_the_case_facts(
    client: httpx.AsyncClient, model: FakeAdapter
) -> None:
    model.responses.append(
        answer_body(
            {
                "text": "The servicer notifies the borrower whether the application is complete.",
                "citations": [1],
                "quote": None,
            },
            facts=["The date the application was received"],
        )
    )
    response = await client.post(
        "/api/v1/guidelines/ask",
        json={
            "question": "The application is missing a document. What must the servicer do?",
            "source_set": "regulation_x",
            "case_id": str(ANGELA),
        },
        headers=auth_headers(Role.LM_SPECIALIST),
    )
    assert response.status_code == 200, response.text
    answer = response.json()
    assert answer["citations"][0]["passage_id"] == "reg-x-1024-41.b"
    assert answer["notice"] == "Not legal advice; confirm with your compliance team."
    assert answer["facts_to_check"] == ["The date the application was received"]
    assert "<case_facts>\n- Case " in model.requests[0].messages[0].content


async def test_a_case_the_role_may_not_see_is_a_404(
    client: httpx.AsyncClient, model: FakeAdapter
) -> None:
    response = await client.post(
        "/api/v1/guidelines/ask",
        json={"question": "How is overtime income evaluated?", "case_id": str(DANIEL)},
        headers=auth_headers(Role.LM_SPECIALIST),
    )
    assert response.status_code == 404
    assert response.json()["message"] == "Case not found"


async def test_a_bad_body_is_a_422(client: httpx.AsyncClient) -> None:
    response = await client.post(
        "/api/v1/guidelines/ask",
        json={"question": "x", "source_set": "nope"},
        headers=auth_headers(Role.UNDERWRITER),
    )
    assert response.status_code == 422

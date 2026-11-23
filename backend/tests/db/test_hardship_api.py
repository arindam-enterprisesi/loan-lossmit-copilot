"""GET /cases/{case_id}/hardship-assessment/latest: Angela Whitfield's letter read into a profile.

The profile is what the borrower says (reason, onset, duration, intent, timeline, enclosed
documents), each item with the quote and the line IDs it came from and whether code found the quote
there (Feature Design 7.5 and 7.7). The v0.5 demo seeds it, with no model call; a later run (D6)
stores the same shape. It never says anything is approved, denied, offered or eligible.
"""

from __future__ import annotations

import copy
import json
import re
import uuid
from typing import Any

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.demo.hardship import SEED_FILE, seed_hardship_profile
from app.db.enums import HardshipSource, Role
from app.db.models import Document, Line, Page
from app.db.seed import case_id, seed
from app.llm.checks import verify_quotes
from app.llm.samples import load_lines
from app.prompts.schemas.hardship import hardship_profile_model, load_hardship_config
from app.services import hardship_runs
from tests.db.conftest import auth_headers

ANGELA = case_id("Angela Whitfield — hardship")  # loss_mitigation
DANIEL = case_id("Daniel Reyes — purchase")  # underwriting
CONFIG = load_hardship_config()
DECISION_WORDS = re.compile(r"\b(approv\w*|den(y|ies|ied)|offer\w*|eligib\w*|qualif\w*)\b", re.I)


@pytest.fixture(autouse=True)
async def seeded(session: AsyncSession) -> None:
    await seed(session, "demo-pass")


def url(case: uuid.UUID | str) -> str:
    return f"/api/v1/cases/{case}/hardship-assessment/latest"


async def get(
    client: httpx.AsyncClient, case: uuid.UUID | str = ANGELA, role: Role = Role.LM_SPECIALIST
) -> httpx.Response:
    return await client.get(url(case), headers=auth_headers(role))


async def add_letter(session: AsyncSession, case: uuid.UUID) -> uuid.UUID:
    """Angela's letter as ingestion leaves it: a document with one page and its numbered lines."""
    document = Document(
        case_id=case,
        file_name="hardship_letter.pdf",
        s3_key=f"k/{uuid.uuid4().hex}",
        sha256=uuid.uuid4().hex * 2,
        mime="application/pdf",
        size_bytes=1,
        page_count=1,
        doc_type="hardship_letter",
    )
    session.add(document)
    await session.flush()
    page = Page(document_id=document.id, page_no=1, image_s3_key="k/p1.png", width=100, height=100)
    session.add(page)
    await session.flush()
    session.add_all(
        Line(
            document_id=document.id,
            page_id=page.id,
            line_ref=f"p{ln.page}-L{ln.line}",
            text=ln.text,
            bbox={"x0": 0, "y0": 0, "x1": 1, "y1": 1},
        )
        for ln in load_lines("angela_hardship_letter")
    )
    await session.flush()
    return document.id


def items(body: dict[str, Any]) -> list[dict[str, Any]]:
    """Every quoted item of a profile in the response."""
    p = body["profile"]
    return [
        p["primary_reason"],
        *p["other_reasons"],
        p["onset"],
        p["duration"],
        p["intent"],
        *p["timeline"],
        *p["enclosed_documents"],
    ]


# --- the seeded profile ---------------------------------------------------------------------


async def test_the_seeded_profile_comes_back_with_every_quote_verified(
    docs_client: httpx.AsyncClient, session: AsyncSession
) -> None:
    letter = await add_letter(session, ANGELA)
    await seed_hardship_profile(session, ANGELA)

    response = await get(docs_client)

    assert response.status_code == 200
    body = response.json()
    assert set(body) == {
        "run_id",
        "source",
        "created_at",
        "letter_document_id",
        "config_version",
        "config_label",
        "profile",
        "flags",
        "budget",
        "measures",
    }
    assert body["source"] == "seeded_sample" and body["letter_document_id"] == str(letter)
    assert (body["config_version"], body["config_label"]) == (CONFIG.version, CONFIG.label)
    assert body["flags"] == []
    assert (body["budget"], body["measures"]) == ([], [])  # filled in on D6

    profile = body["profile"]
    assert set(profile) == {
        "primary_reason",
        "other_reasons",
        "onset",
        "duration",
        "intent",
        "timeline",
        "enclosed_documents",
    }
    assert profile["primary_reason"] == {
        "quote": "cut my hours from 40 to 30 a week in July",
        "lines": ["p1-L6"],
        "verified": True,
        "check_flags": [],
        "category": "reduction_in_income",
        "category_label": "Reduction in income",
        "sensitive": False,
        "financial_effect": "hours and pay reduced by a quarter",
    }
    assert (profile["onset"]["as_stated"], profile["onset"]["month"]) == ("July", "2026-07")
    assert (profile["duration"]["category"], profile["intent"]["category"]) == ("unknown", "keep")
    assert profile["other_reasons"] == []
    assert [e["lines"] for e in profile["timeline"]] == [["p1-L6"], ["p1-L7"]]
    assert [d["document"] for d in profile["enclosed_documents"]] == [
        "Mortgage assistance application",
        "Pay stubs",
        "Bank statements",
    ]
    # Rule 2: every item names the lines it came from, and code found each quote there.
    assert len(items(body)) == 9
    assert all(item["verified"] and item["lines"] for item in items(body))


async def test_without_the_letter_uploaded_the_profile_is_checked_against_the_sample_lines(
    docs_client: httpx.AsyncClient, session: AsyncSession
) -> None:
    await seed_hardship_profile(session, ANGELA)

    body = (await get(docs_client)).json()

    assert body["letter_document_id"] is None  # nothing to highlight on yet
    assert all(item["verified"] for item in items(body))


async def test_seeding_twice_keeps_one_profile(
    docs_client: httpx.AsyncClient, session: AsyncSession
) -> None:
    first = await seed_hardship_profile(session, ANGELA)
    second = await seed_hardship_profile(session, ANGELA)

    assert second.id == first.id
    assert (await get(docs_client)).json()["run_id"] == str(first.run_id)


async def test_the_response_never_uses_decision_wording(
    docs_client: httpx.AsyncClient, session: AsyncSession
) -> None:
    await seed_hardship_profile(session, ANGELA)

    text = (await get(docs_client)).text

    assert DECISION_WORDS.findall(text) == []


# --- a quote that is not on its line ---------------------------------------------------------


async def store(
    session: AsyncSession, case: uuid.UUID, change: Any = None, document: uuid.UUID | None = None
) -> Any:
    """A model-source profile (as D6 will store one), optionally with the seed's data changed."""
    data = copy.deepcopy(json.loads(SEED_FILE.read_text(encoding="utf-8"))["profile"])
    if change:
        change(data)
    profile = hardship_profile_model(CONFIG.keys).model_validate(data)
    checks = verify_quotes(
        profile, load_lines("angela_hardship_letter"), max_quote_chars=CONFIG.max_quote_chars
    )
    return await hardship_runs.store_profile(
        session,
        case_id=case,
        document_id=document,
        profile=profile,
        checks=checks,
        config=CONFIG,
        source=HardshipSource.MODEL,
        created_by=None,
    )


async def test_a_quote_that_is_not_on_its_line_is_shown_as_unverified_with_a_flag(
    docs_client: httpx.AsyncClient, session: AsyncSession
) -> None:
    letter = await add_letter(session, ANGELA)

    def invent(data: dict[str, Any]) -> None:
        data["intent"]["quote"] = "I plan to sell the house"  # not in line 14

    await store(session, ANGELA, invent, letter)

    body = (await get(docs_client)).json()

    assert body["source"] == "model"
    intent = body["profile"]["intent"]
    assert (intent["verified"], intent["check_flags"]) == (False, ["unverified_quote"])
    assert [i["verified"] for i in items(body)].count(False) == 1
    [flag] = body["flags"]
    assert flag["code"] == "unverified_quote" and flag["severity"] == "warning"
    assert flag["message"] == "Intent: we couldn't find this quote in the lines it cites."
    # The flag points at the cited line of the letter (rule 2).
    assert flag["evidence"] == {
        "document_id": str(letter),
        "page": 1,
        "line_ids": ["p1-L14"],
        "bbox": None,
    }


async def test_a_quote_citing_a_line_that_does_not_exist_is_flagged_without_evidence(
    docs_client: httpx.AsyncClient, session: AsyncSession
) -> None:
    def cite_nothing_real(data: dict[str, Any]) -> None:
        data["onset"]["lines"] = ["p9-L99"]

    await store(session, ANGELA, cite_nothing_real)

    body = (await get(docs_client)).json()

    assert body["profile"]["onset"]["verified"] is False
    [flag] = body["flags"]
    assert flag["message"] == "Onset: we couldn't find this quote in the lines it cites."
    assert flag["evidence"] is None  # no letter on the case, so nothing to point at


async def test_a_failed_quote_makes_exactly_one_flag_on_its_run(session: AsyncSession) -> None:
    def invent(data: dict[str, Any]) -> None:
        data["intent"]["quote"] = "I plan to sell the house"

    await store(session, ANGELA, invent)

    view = await hardship_runs.latest(session, ANGELA)

    assert view is not None and [f.code for f in view.flags] == ["unverified_quote"]


# --- which run is the latest -----------------------------------------------------------------


async def test_the_newest_run_is_the_latest(
    docs_client: httpx.AsyncClient, session: AsyncSession
) -> None:
    await seed_hardship_profile(session, ANGELA)

    def sell(data: dict[str, Any]) -> None:
        data["intent"] = {
            "quote": "I want to keep my home",
            "lines": ["p1-L14"],
            "category": "sell",
        }

    newer = await store(session, ANGELA, sell)

    body = (await get(docs_client)).json()

    assert body["run_id"] == str(newer.run_id) and body["source"] == "model"
    assert body["profile"]["intent"]["category"] == "sell"


# --- who may see it, and what is not there ---------------------------------------------------


async def test_a_case_with_no_profile_is_a_404(docs_client: httpx.AsyncClient) -> None:
    response = await get(docs_client)

    assert response.status_code == 404
    assert response.json()["code"] == "not_found"
    assert "hardship" in response.json()["message"].lower()


async def test_the_case_of_another_pillar_is_a_404_for_the_loss_mitigation_specialist(
    docs_client: httpx.AsyncClient, session: AsyncSession
) -> None:
    await seed_hardship_profile(session, DANIEL)  # even a stray profile on an underwriting case

    response = await get(docs_client, DANIEL, Role.LM_SPECIALIST)

    assert response.status_code == 404 and response.json()["message"] == "Case not found"


async def test_the_underwriter_cannot_see_the_loss_mitigation_case(
    docs_client: httpx.AsyncClient, session: AsyncSession
) -> None:
    await seed_hardship_profile(session, ANGELA)

    response = await get(docs_client, ANGELA, Role.UNDERWRITER)

    assert response.status_code == 404 and response.json()["message"] == "Case not found"
    assert "profile" not in response.json()


async def test_the_admin_may_look(docs_client: httpx.AsyncClient, session: AsyncSession) -> None:
    await seed_hardship_profile(session, ANGELA)
    assert (await get(docs_client, ANGELA, Role.ADMIN)).status_code == 200


@pytest.mark.parametrize("case", [uuid.uuid4(), "not-a-uuid"])
async def test_an_unknown_or_malformed_case_is_a_404(
    docs_client: httpx.AsyncClient, case: uuid.UUID | str
) -> None:
    assert (await get(docs_client, case)).status_code == 404


async def test_no_token_is_a_401(docs_client: httpx.AsyncClient) -> None:
    assert (await docs_client.get(url(ANGELA))).status_code == 401

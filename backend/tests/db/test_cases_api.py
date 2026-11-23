"""Cases API against the real schema: roles, visibility, profile and audit events."""

from __future__ import annotations

import re
import uuid
from typing import Any

import httpx
import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.enums import Role
from app.db.seed import DEMO_USERS, case_id, seed, user_id
from app.services.security import CurrentUser, create_access_token
from tests.db.conftest import insert_document

PASSWORD = "demo-pass"
DANIEL = case_id("Daniel Reyes — purchase")  # underwriting
ANGELA = case_id("Angela Whitfield — hardship")  # loss_mitigation

PROFILE = {
    "borrower_names": ["Daniel Reyes"],
    "employment_type": "wage_earner",
    "reference_date": "2026-10-12",
}

_NAMES = {username: (name, role) for username, name, role in DEMO_USERS}
USERNAME = {
    Role.UNDERWRITER: "underwriter",
    Role.LM_SPECIALIST: "lm_specialist",
    Role.ADMIN: "admin",
}


def auth(role: Role) -> dict[str, str]:
    username = USERNAME[role]
    name, _ = _NAMES[username]
    token = create_access_token(CurrentUser(id=str(user_id(username)), name=name, role=role))
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture(autouse=True)
async def seeded(session: AsyncSession) -> None:
    await seed(session, PASSWORD)


async def audit_rows(session: AsyncSession, case: uuid.UUID) -> list[Any]:
    result = await session.execute(
        sa.text(
            "SELECT actor_id, role, action, entity_type, entity_id, before, after "
            "FROM audit_events WHERE case_id = :c ORDER BY id"
        ),
        {"c": case},
    )
    return list(result.all())


# --- create ------------------------------------------------------------------------------


async def test_create_case(client: httpx.AsyncClient, session: AsyncSession) -> None:
    response = await client.post(
        "/api/v1/cases",
        json={"title": "  New borrower — purchase ", "pillar": "underwriting"},
        headers=auth(Role.UNDERWRITER),
    )

    assert response.status_code == 201
    body = response.json()
    assert set(body) == {
        "id",
        "case_ref",
        "title",
        "pillar",
        "profile",
        "document_count",
        "created_at",
    }
    assert re.fullmatch(r"LP-[0-9]{4,}", body["case_ref"])  # the contract's pattern
    assert body["title"] == "New borrower — purchase"
    assert (body["pillar"], body["profile"], body["document_count"]) == ("underwriting", None, 0)
    created_by = await session.scalar(
        sa.text("SELECT created_by FROM cases WHERE id = :c"), {"c": body["id"]}
    )
    assert created_by == user_id("underwriter")


async def test_new_cases_get_a_ref_from_their_pillars_sequence(
    client: httpx.AsyncClient, session: AsyncSession
) -> None:
    # case_ref is in the contract's Case (since #6), so it is sent and equals the stored one.
    refs = []
    for role, pillar in [
        (Role.UNDERWRITER, "underwriting"),
        (Role.UNDERWRITER, "underwriting"),
        (Role.LM_SPECIALIST, "loss_mitigation"),
    ]:
        response = await client.post(
            "/api/v1/cases", json={"title": "T", "pillar": pillar}, headers=auth(role)
        )
        stored = await session.scalar(
            sa.text("SELECT case_ref FROM cases WHERE id = :c"), {"c": response.json()["id"]}
        )
        assert response.json()["case_ref"] == stored
        refs.append(stored)

    assert all(re.fullmatch(r"(LP|LM)-\d{4,}", ref) for ref in refs)
    assert [ref[:2] for ref in refs] == ["LP", "LP", "LM"]
    # Never the seeded refs, and never repeated (the seed moved the sequences past them).
    assert len(set(refs)) == 3
    assert not {"LP-0001", "LM-0001"} & set(refs)


@pytest.mark.parametrize(
    ("role", "pillar", "allowed"),
    [
        (Role.UNDERWRITER, "underwriting", True),
        (Role.UNDERWRITER, "loss_mitigation", False),
        (Role.LM_SPECIALIST, "loss_mitigation", True),
        (Role.LM_SPECIALIST, "underwriting", False),
        (Role.ADMIN, "underwriting", True),
        (Role.ADMIN, "loss_mitigation", True),
    ],
)
async def test_creating_in_a_pillar_depends_on_role(
    client: httpx.AsyncClient, role: Role, pillar: str, allowed: bool
) -> None:
    response = await client.post(
        "/api/v1/cases", json={"title": "T", "pillar": pillar}, headers=auth(role)
    )
    assert response.status_code == (201 if allowed else 403)
    if not allowed:
        assert response.json()["code"] == "forbidden"


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"title": "T"},
        {"pillar": "underwriting"},
        {"title": "   ", "pillar": "underwriting"},
        {"title": "x" * 201, "pillar": "underwriting"},
        {"title": "T", "pillar": "loan_processing"},
    ],
)
async def test_create_validation(client: httpx.AsyncClient, payload: dict[str, str]) -> None:
    response = await client.post("/api/v1/cases", json=payload, headers=auth(Role.ADMIN))
    assert response.status_code == 422
    assert response.json()["code"] == "validation_failed"


async def test_every_endpoint_needs_a_token(client: httpx.AsyncClient) -> None:
    for method, path in [
        ("POST", "/api/v1/cases"),
        ("GET", "/api/v1/cases"),
        ("GET", f"/api/v1/cases/{DANIEL}"),
        ("PUT", f"/api/v1/cases/{DANIEL}/profile"),
    ]:
        response = await client.request(method, path)
        assert response.status_code == 401, (method, path)
        assert response.json()["code"] == "unauthorized"


async def test_create_writes_an_audit_event(
    client: httpx.AsyncClient, session: AsyncSession
) -> None:
    response = await client.post(
        "/api/v1/cases",
        json={"title": "Audited", "pillar": "loss_mitigation"},
        headers=auth(Role.LM_SPECIALIST),
    )
    new_id = uuid.UUID(response.json()["id"])

    [event] = await audit_rows(session, new_id)
    assert event.actor_id == user_id("lm_specialist")
    assert event.role == "lm_specialist"
    assert (event.action, event.entity_type, event.entity_id) == ("case.created", "case", new_id)
    after = dict(event.after)
    assert re.fullmatch(r"LM-\d{4,}", after.pop("case_ref"))
    assert after == {"title": "Audited", "pillar": "loss_mitigation", "status": "open"}


# --- list --------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("role", "titles"),
    [
        (Role.UNDERWRITER, ["Daniel Reyes — purchase"]),
        (Role.LM_SPECIALIST, ["Angela Whitfield — hardship"]),
        (Role.ADMIN, ["Angela Whitfield — hardship", "Daniel Reyes — purchase"]),
    ],
)
async def test_list_shows_only_what_the_role_may_see(
    client: httpx.AsyncClient, role: Role, titles: list[str]
) -> None:
    response = await client.get("/api/v1/cases", headers=auth(role))
    assert response.status_code == 200
    assert sorted(item["title"] for item in response.json()["items"]) == titles


async def test_list_pillar_filter(client: httpx.AsyncClient) -> None:
    admin = auth(Role.ADMIN)
    only_lm = await client.get("/api/v1/cases", params={"pillar": "loss_mitigation"}, headers=admin)
    assert [i["pillar"] for i in only_lm.json()["items"]] == ["loss_mitigation"]

    # Filtering on a pillar the caller cannot see is empty, not an error.
    hidden = await client.get(
        "/api/v1/cases", params={"pillar": "loss_mitigation"}, headers=auth(Role.UNDERWRITER)
    )
    assert hidden.status_code == 200
    assert hidden.json() == {"items": []}

    bad = await client.get("/api/v1/cases", params={"pillar": "nope"}, headers=admin)
    assert bad.status_code == 422


async def test_document_count(client: httpx.AsyncClient, session: AsyncSession) -> None:
    conn = await session.connection()
    await insert_document(conn, DANIEL)
    await insert_document(conn, DANIEL)

    listed = await client.get("/api/v1/cases", headers=auth(Role.UNDERWRITER))
    assert listed.json()["items"][0]["document_count"] == 2
    one = await client.get(f"/api/v1/cases/{DANIEL}", headers=auth(Role.UNDERWRITER))
    assert one.json()["document_count"] == 2


# --- get ---------------------------------------------------------------------------------


async def test_get_visible_case(client: httpx.AsyncClient) -> None:
    response = await client.get(f"/api/v1/cases/{DANIEL}", headers=auth(Role.UNDERWRITER))
    assert response.status_code == 200
    body = response.json()
    assert body["id"] == str(DANIEL)
    assert (body["pillar"], body["profile"]) == ("underwriting", None)


@pytest.mark.parametrize("target", [str(uuid.uuid4()), "not-a-uuid", "123"])
async def test_get_unknown_or_malformed_id_is_404(client: httpx.AsyncClient, target: str) -> None:
    response = await client.get(f"/api/v1/cases/{target}", headers=auth(Role.ADMIN))
    assert response.status_code == 404
    assert response.json() == {"code": "not_found", "message": "Case not found"}


async def test_a_case_you_cannot_see_looks_like_one_that_does_not_exist(
    client: httpx.AsyncClient,
) -> None:
    hidden = await client.get(f"/api/v1/cases/{ANGELA}", headers=auth(Role.UNDERWRITER))
    missing = await client.get(f"/api/v1/cases/{uuid.uuid4()}", headers=auth(Role.UNDERWRITER))
    assert hidden.status_code == missing.status_code == 404
    assert hidden.json() == missing.json()


# --- profile -----------------------------------------------------------------------------


async def test_put_profile_then_read_it_back(
    client: httpx.AsyncClient, session: AsyncSession
) -> None:
    put = await client.put(
        f"/api/v1/cases/{DANIEL}/profile",
        json={**PROFILE, "borrower_names": ["  Daniel Reyes ", "Maria Reyes"]},
        headers=auth(Role.UNDERWRITER),
    )
    assert put.status_code == 200
    expected = {**PROFILE, "borrower_names": ["Daniel Reyes", "Maria Reyes"]}
    assert put.json() == expected

    got = await client.get(f"/api/v1/cases/{DANIEL}", headers=auth(Role.UNDERWRITER))
    assert got.json()["profile"] == expected


async def test_profile_update_is_audited_with_before_and_after(
    client: httpx.AsyncClient, session: AsyncSession
) -> None:
    headers = auth(Role.UNDERWRITER)
    await client.put(f"/api/v1/cases/{DANIEL}/profile", json=PROFILE, headers=headers)
    changed = {**PROFILE, "employment_type": "self_employed"}
    await client.put(f"/api/v1/cases/{DANIEL}/profile", json=changed, headers=headers)

    first, second = await audit_rows(session, DANIEL)
    assert first.action == second.action == "case.profile_updated"
    assert first.actor_id == user_id("underwriter")
    assert (first.role, first.entity_type, first.entity_id) == ("underwriter", "case", DANIEL)
    assert first.before == {"borrower_names": None, "employment_type": None, "reference_date": None}
    assert first.after["employment_type"] == "wage_earner"
    # The earlier value is not overwritten away: it lives on in the next event's "before".
    assert second.before == first.after
    assert second.after["employment_type"] == "self_employed"


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {**PROFILE, "borrower_names": []},
        {**PROFILE, "borrower_names": ["  "]},
        {**PROFILE, "borrower_names": ["x" * 201]},
        {**PROFILE, "employment_type": "astronaut"},
        {**PROFILE, "reference_date": "12/10/2026"},
        {k: v for k, v in PROFILE.items() if k != "reference_date"},
    ],
)
async def test_profile_validation(
    client: httpx.AsyncClient, session: AsyncSession, payload: dict[str, Any]
) -> None:
    response = await client.put(
        f"/api/v1/cases/{DANIEL}/profile", json=payload, headers=auth(Role.UNDERWRITER)
    )
    assert response.status_code == 422
    assert response.json()["code"] == "validation_failed"
    assert await audit_rows(session, DANIEL) == []


async def test_profile_of_a_case_you_cannot_see_is_404_and_changes_nothing(
    client: httpx.AsyncClient, session: AsyncSession
) -> None:
    response = await client.put(
        f"/api/v1/cases/{ANGELA}/profile", json=PROFILE, headers=auth(Role.UNDERWRITER)
    )
    assert response.status_code == 404
    assert await audit_rows(session, ANGELA) == []
    row = await session.execute(
        sa.text("SELECT borrower_names FROM cases WHERE id = :c"), {"c": ANGELA}
    )
    assert row.scalar_one() is None


async def test_a_partly_filled_profile_reads_back_as_null(
    client: httpx.AsyncClient, session: AsyncSession
) -> None:
    await session.execute(
        sa.text(
            "UPDATE cases SET borrower_names = CAST('[\"Daniel Reyes\"]' AS jsonb) WHERE id = :c"
        ),
        {"c": DANIEL},
    )
    got = await client.get(f"/api/v1/cases/{DANIEL}", headers=auth(Role.UNDERWRITER))
    assert got.json()["profile"] is None

"""POST /api/v1/auth/login against the real schema and the real seed."""

from __future__ import annotations

import httpx
import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.enums import Role
from app.db.seed import DEMO_USERS, seed, user_id
from app.services.auth_config import get_auth_config
from app.services.security import decode_access_token

PASSWORD = "demo-pass"
LOGIN = "/api/v1/auth/login"


@pytest.fixture(autouse=True)
async def seeded(session: AsyncSession) -> None:
    await seed(session, PASSWORD)


@pytest.mark.parametrize(("username", "name", "role"), DEMO_USERS)
async def test_each_demo_user_can_log_in(
    client: httpx.AsyncClient, username: str, name: str, role: Role
) -> None:
    response = await client.post(LOGIN, json={"username": username, "password": PASSWORD})

    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"access_token", "token_type", "expires_in", "user"}
    assert body["token_type"] == "bearer"
    assert body["expires_in"] == get_auth_config().access_token_minutes * 60
    assert body["user"] == {"id": str(user_id(username)), "name": name, "role": role.value}

    current = decode_access_token(body["access_token"])
    assert (current.id, current.name, current.role) == (str(user_id(username)), name, role)


async def test_response_never_contains_the_password_or_its_hash(client: httpx.AsyncClient) -> None:
    response = await client.post(LOGIN, json={"username": "admin", "password": PASSWORD})
    assert PASSWORD not in response.text
    assert "scrypt" not in response.text
    assert "password" not in response.text


async def test_email_is_stored_but_never_returned(
    client: httpx.AsyncClient, session: AsyncSession
) -> None:
    # users.email exists (schema doc) but the contract's login user is only id, name and role.
    await session.execute(
        sa.text("UPDATE users SET email = 'admin@example.test' WHERE username = 'admin'")
    )
    response = await client.post(LOGIN, json={"username": "admin", "password": PASSWORD})
    assert set(response.json()["user"]) == {"id", "name", "role"}
    assert "email" not in response.text and "example.test" not in response.text


async def test_wrong_password_and_unknown_user_look_identical(client: httpx.AsyncClient) -> None:
    wrong = await client.post(LOGIN, json={"username": "admin", "password": "nope"})
    unknown = await client.post(LOGIN, json={"username": "nobody", "password": PASSWORD})

    assert wrong.status_code == unknown.status_code == 401
    assert wrong.json() == unknown.json()
    assert wrong.json() == {
        "code": "invalid_credentials",
        "message": "Incorrect username or password",
    }


async def test_usernames_are_case_sensitive(client: httpx.AsyncClient) -> None:
    response = await client.post(LOGIN, json={"username": "Admin", "password": PASSWORD})
    assert response.status_code == 401


@pytest.mark.parametrize(
    "payload", [{}, {"username": "admin"}, {"password": PASSWORD}, {"username": "", "password": ""}]
)
async def test_invalid_body_is_422_in_the_contract_shape(
    client: httpx.AsyncClient, payload: dict[str, str]
) -> None:
    response = await client.post(LOGIN, json=payload)
    assert response.status_code == 422
    body = response.json()
    assert body["code"] == "validation_failed"
    assert body["details"]["errors"]
    assert PASSWORD not in response.text


async def test_login_needs_no_token_and_health_is_unaffected(client: httpx.AsyncClient) -> None:
    assert (await client.get("/health")).json() == {"status": "ok"}
    # Not under /api/v1, and not the contract's path.
    assert (await client.post("/auth/login", json={})).status_code == 404

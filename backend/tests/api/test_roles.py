"""Current-user dependency and per-router role checks. No database needed.

The real app has no role-restricted routers yet, so these tests mount throwaway
routers built with the same ``require_roles`` dependency that feature routers will use.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import Annotated

import httpx
import pytest
import pytest_asyncio
from fastapi import APIRouter, Depends, FastAPI

from app.api.deps import get_current_user, require_roles
from app.api.errors import register_error_handlers
from app.db.enums import Role
from app.services.security import CurrentUser, create_access_token

USERS = {
    role: CurrentUser(id=f"id-{role.value}", name=role.value.title(), role=role) for role in Role
}

# path -> roles allowed there
ROUTES = {
    "/underwriting/ping": {Role.UNDERWRITER},
    "/loss-mitigation/ping": {Role.LM_SPECIALIST},
    "/shared/ping": {Role.UNDERWRITER, Role.LM_SPECIALIST},
    "/admin/ping": {Role.ADMIN},
}


def _router(prefix: str, *roles: Role) -> APIRouter:
    router = APIRouter(prefix=prefix, dependencies=[Depends(require_roles(*roles))])

    @router.get("/ping")
    async def ping() -> dict[str, str]:
        return {"ok": "true"}

    return router


def _app() -> FastAPI:
    app = FastAPI()
    register_error_handlers(app)
    app.include_router(_router("/underwriting", Role.UNDERWRITER))
    app.include_router(_router("/loss-mitigation", Role.LM_SPECIALIST))
    app.include_router(_router("/shared", Role.UNDERWRITER, Role.LM_SPECIALIST))
    app.include_router(_router("/admin", Role.ADMIN))

    @app.get("/me")
    async def me(user: Annotated[CurrentUser, Depends(get_current_user)]) -> dict[str, str]:
        return {"id": user.id, "name": user.name, "role": user.role.value}

    return app


@pytest_asyncio.fixture
async def client() -> AsyncIterator[httpx.AsyncClient]:
    transport = httpx.ASGITransport(app=_app())
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


def _bearer(user: CurrentUser) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(user)}"}


@pytest.mark.parametrize("role", list(Role))
@pytest.mark.parametrize("path", list(ROUTES))
async def test_each_role_against_each_router(
    client: httpx.AsyncClient, role: Role, path: str
) -> None:
    response = await client.get(path, headers=_bearer(USERS[role]))
    if role in ROUTES[path]:
        assert response.status_code == 200
    else:
        assert response.status_code == 403
        assert response.json() == {
            "code": "forbidden",
            "message": "Your role cannot access this resource",
        }


async def test_admin_is_not_implicitly_allowed(client: httpx.AsyncClient) -> None:
    response = await client.get("/underwriting/ping", headers=_bearer(USERS[Role.ADMIN]))
    assert response.status_code == 403


async def test_current_user_comes_from_the_token(client: httpx.AsyncClient) -> None:
    response = await client.get("/me", headers=_bearer(USERS[Role.LM_SPECIALIST]))
    assert response.json() == {
        "id": "id-lm_specialist",
        "name": "Lm_Specialist",
        "role": "lm_specialist",
    }


async def test_missing_token_is_401_in_the_contract_shape(client: httpx.AsyncClient) -> None:
    response = await client.get("/underwriting/ping")
    assert response.status_code == 401
    assert response.json() == {"code": "unauthorized", "message": "Missing or invalid token"}
    assert response.headers["www-authenticate"] == "Bearer"


@pytest.mark.parametrize(
    "header",
    ["Bearer", "Bearer not-a-jwt", "Basic dXNlcjpwYXNz", "bearer", "Token abc"],
)
async def test_bad_authorization_header_is_401(client: httpx.AsyncClient, header: str) -> None:
    response = await client.get("/me", headers={"Authorization": header})
    assert response.status_code == 401
    assert response.json()["code"] == "unauthorized"


async def test_expired_token_is_401(client: httpx.AsyncClient) -> None:
    old = datetime.now(UTC) - timedelta(days=2)
    token = create_access_token(USERS[Role.ADMIN], expires_minutes=5, now=old)
    response = await client.get("/admin/ping", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 401


async def test_token_from_another_secret_is_401(client: httpx.AsyncClient) -> None:
    token = create_access_token(USERS[Role.ADMIN], secret="not-our-secret")
    response = await client.get("/admin/ping", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 401


async def test_unknown_path_uses_the_contract_error_shape(client: httpx.AsyncClient) -> None:
    response = await client.get("/nope")
    assert response.status_code == 404
    assert set(response.json()) == {"code", "message"}
    assert response.json()["code"] == "not_found"

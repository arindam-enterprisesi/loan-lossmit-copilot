"""CORS: the browser app on another origin may call the API (and nobody else's page may).

The frontend runs on http://localhost:3000 and the API on http://localhost:8000, which a browser
treats as different origins. The login token travels in the ``Authorization`` header, so no cookies
or credentials are involved.
"""

from __future__ import annotations

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.main import app, install_cors
from app.settings import Settings, get_settings

ALLOWED = "http://localhost:3000"
OTHER = "http://evil.example"


def small_app(origins: list[str]) -> TestClient:
    """A throwaway app, so these tests do not depend on the developer's own CORS_ORIGINS."""
    demo = FastAPI()
    install_cors(demo, origins)

    @demo.get("/ping")
    async def ping() -> dict[str, str]:
        return {"ok": "yes"}

    return TestClient(demo)


def preflight(client: TestClient, origin: str, method: str = "PATCH") -> httpx.Response:
    return client.options(
        "/ping",
        headers={
            "Origin": origin,
            "Access-Control-Request-Method": method,
            "Access-Control-Request-Headers": "authorization,content-type",
        },
    )


def test_a_preflight_from_an_allowed_origin_gets_the_allow_headers() -> None:
    response = preflight(small_app([ALLOWED]), ALLOWED)
    assert response.status_code == 200
    headers = response.headers
    assert headers["access-control-allow-origin"] == ALLOWED
    allowed_methods = {m.strip() for m in headers["access-control-allow-methods"].split(",")}
    assert {"GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"} <= allowed_methods
    sent = headers["access-control-allow-headers"].split(",")
    allowed_headers = {h.strip().lower() for h in sent}
    assert {"authorization", "content-type"} <= allowed_headers


def test_no_credentials_are_allowed() -> None:
    # The bearer token is a header, not a cookie, so cross-origin cookies stay off.
    response = preflight(small_app([ALLOWED]), ALLOWED)
    assert "access-control-allow-credentials" not in response.headers


@pytest.mark.parametrize("method", ["GET", "POST", "PUT", "PATCH", "DELETE"])
def test_every_api_method_may_be_preflighted(method: str) -> None:
    response = preflight(small_app([ALLOWED]), ALLOWED, method)
    assert response.status_code == 200


def test_a_preflight_from_any_other_origin_is_refused() -> None:
    response = preflight(small_app([ALLOWED]), OTHER)
    assert response.status_code == 400
    assert "access-control-allow-origin" not in response.headers


def test_a_plain_request_is_marked_for_an_allowed_origin_only() -> None:
    client = small_app([ALLOWED])
    ok = client.get("/ping", headers={"Origin": ALLOWED})
    assert ok.headers["access-control-allow-origin"] == ALLOWED
    other = client.get("/ping", headers={"Origin": OTHER})
    assert other.status_code == 200  # CORS is enforced by the browser, not by refusing the call
    assert "access-control-allow-origin" not in other.headers


def test_several_origins_can_be_allowed() -> None:
    client = small_app([ALLOWED, "http://127.0.0.1:3000"])
    for origin in (ALLOWED, "http://127.0.0.1:3000"):
        response = client.get("/ping", headers={"Origin": origin})
        assert response.headers["access-control-allow-origin"] == origin


def test_with_no_origins_nothing_is_allowed() -> None:
    client = small_app([])
    response = client.get("/ping", headers={"Origin": ALLOWED})
    assert response.status_code == 200
    assert "access-control-allow-origin" not in response.headers


def test_the_real_app_uses_the_configured_origins() -> None:
    allowed = get_settings().cors_origin_list
    assert allowed, "CORS_ORIGINS must name at least one origin"
    client = TestClient(app)
    response = client.options(
        "/api/v1/auth/login",
        headers={"Origin": allowed[0], "Access-Control-Request-Method": "POST"},
    )
    assert response.headers["access-control-allow-origin"] == allowed[0]
    refused = client.options(
        "/api/v1/auth/login",
        headers={"Origin": OTHER, "Access-Control-Request-Method": "POST"},
    )
    assert "access-control-allow-origin" not in refused.headers


# --- the setting ---------------------------------------------------------------------------


def test_the_default_origin_is_the_local_frontend(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CORS_ORIGINS", raising=False)
    assert Settings(_env_file=None).cors_origin_list == [ALLOWED]


def test_the_origin_list_is_comma_separated_and_trimmed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CORS_ORIGINS", " http://localhost:3000 ,https://demo.example.com/,, ")
    assert Settings(_env_file=None).cors_origin_list == [
        "http://localhost:3000",
        "https://demo.example.com",  # a trailing slash is not part of an origin
    ]


def test_a_blank_setting_means_no_origins(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CORS_ORIGINS", "  ")
    assert Settings(_env_file=None).cors_origin_list == []


@pytest.mark.parametrize("value", ["*", "http://localhost:3000,*"])
def test_a_wildcard_is_rejected(monkeypatch: pytest.MonkeyPatch, value: str) -> None:
    monkeypatch.setenv("CORS_ORIGINS", value)
    with pytest.raises(ValueError, match="wildcard"):
        Settings(_env_file=None)

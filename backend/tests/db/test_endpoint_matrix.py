"""Every endpoint the API serves, held to the same four rules (D7, C12).

For each endpoint: no token is a 401; a role that may not use it is a 403 and the administrator, who
makes no case decisions, is among them where the action is a person's; a case the role may not see
is a 404 that says "Case not found" (the other pillar's case is hidden, not forbidden); and a body
that is not valid is a 422 that names what is wrong. The success case of each endpoint is in its own
router's tests and in the two demo stories (``test_demo_stories.py``): a last test here fails if an
endpoint has none.

The table is the list of operations the app serves, so a new endpoint cannot be added without a row
(``test_the_table_is_every_operation_the_app_serves``).
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.enums import Role
from app.db.seed import case_id, seed
from app.main import app
from tests.db.conftest import auth_headers
from tests.db.test_documents_api import upload

DANIEL = case_id("Daniel Reyes — purchase")  # Pillar 1: the underwriter's
ANGELA = case_id("Angela Whitfield — hardship")  # Pillar 2: the loss mitigation specialist's
ANY = frozenset({Role.UNDERWRITER, Role.LM_SPECIALIST, Role.ADMIN})
ONLY_LM = frozenset({Role.LM_SPECIALIST})
ONLY_UW = frozenset({Role.UNDERWRITER})
# One body that no schema accepts: a wrong enum, a wrong type, an empty string, an unknown key.
NONSENSE: dict[str, Any] = {
    "action": "nope",
    "doc_type": "nope",
    "decision": "nope",
    "status": "nope",
    "priority": "nope",
    "included": "nope",
    "counts_toward_dti": "nope",
    "category": "nope",
    "checklist_id": "",
    "text": "",
    "reason": "",
    "purpose": "",
    "property_value": "nope",
    "borrower_names": "nope",
    "employment_type": "nope",
    "reference_date": "nope",
    "adjusted_amount": "nope",
    "primary_reason": "nope",
    "intent": "nope",
    "unknown_key": 1,
}
LOAN_SCENARIO = {
    "purpose": "purchase",
    "occupancy": "primary residence",
    "property_value": "400000.00",
    "loan_amount": "360000.00",
    "proposed_housing_payment": "2400.00",
    "funds_to_close": "36500.00",
}


@dataclass(frozen=True)
class Endpoint:
    method: str
    path: str  # as served, with {case_id} and other parameters
    roles: frozenset[Role] = ANY  # who passes the role gate
    body: dict[str, Any] | None = None  # a valid body, for the 404 check on endpoints that take one
    takes_body: bool = False
    anonymous: bool = False  # no token needed (login, health)
    special: str = ""  # why the generic checks do not apply

    @property
    def key(self) -> tuple[str, str]:
        return self.method, self.path

    @property
    def is_case(self) -> bool:
        return "{case_id}" in self.path


def ep(method: str, path: str, **kw: Any) -> Endpoint:
    return Endpoint(method, path, **kw)


C = "/api/v1/cases/{case_id}"
ENDPOINTS: tuple[Endpoint, ...] = (
    ep("POST", "/api/v1/auth/login", anonymous=True, special="login takes credentials, not a case"),
    ep("GET", "/health", anonymous=True, special="not under /api/v1"),
    ep("GET", "/api/v1/cases", special="lists the cases the role may see"),
    ep("POST", "/api/v1/cases", special="creates a case, not one of the existing two"),
    ep("GET", C),
    ep(
        "PUT",
        f"{C}/profile",
        takes_body=True,
        body={
            "borrower_names": ["A Borrower"],
            "employment_type": "wage_earner",
            "reference_date": "2026-10-12",
        },
    ),
    # documents
    ep("GET", f"{C}/documents"),
    ep("POST", f"{C}/documents", special="multipart upload: see the test below"),
    ep("GET", f"{C}/documents/{{document_id}}/extraction"),
    ep(
        "PATCH",
        f"{C}/documents/{{document_id}}/fields/{{field_name}}",
        takes_body=True,
        body={"action": "confirm", "expected_version": 1},
    ),
    ep("GET", f"{C}/documents/{{document_id}}/pages/{{page}}", special="a page image, not JSON"),
    ep("PUT", f"{C}/documents/{{document_id}}/type", takes_body=True, body={"doc_type": "w2"}),
    # completeness
    ep(
        "POST", f"{C}/completeness", takes_body=True, body={"checklist_id": "pillar1-wage-earner@1"}
    ),
    ep("GET", f"{C}/completeness/latest"),
    ep(
        "PATCH",
        f"{C}/completeness/latest/items/{{item_id}}",
        takes_body=True,
        body={"action": "clear"},
    ),
    # income
    ep("POST", f"{C}/income-analysis"),
    ep("GET", f"{C}/income-analysis/latest"),
    ep(
        "PATCH",
        f"{C}/income-analysis/latest/components/{{component_id}}",
        takes_body=True,
        body={"included": True, "reason": "checked"},
    ),
    # assets and liabilities
    ep("GET", f"{C}/loan-scenario"),
    ep("PUT", f"{C}/loan-scenario", takes_body=True, body=LOAN_SCENARIO),
    ep("POST", f"{C}/asset-liability"),
    ep("GET", f"{C}/asset-liability/latest"),
    ep(
        "PATCH",
        f"{C}/asset-liability/latest/transactions/{{transaction_id}}",
        takes_body=True,
        body={"sourced": True, "reason": "checked"},
    ),
    ep(
        "PATCH",
        f"{C}/asset-liability/latest/obligations/{{obligation_id}}",
        takes_body=True,
        body={"counts_toward_dti": False, "reason": "checked"},
    ),
    # credit
    ep("POST", f"{C}/credit-analysis"),
    ep("GET", f"{C}/credit-analysis/latest"),
    # underwriting report
    ep("GET", f"{C}/underwriting-report/latest"),
    ep(
        "POST",
        f"{C}/underwriting-report/latest/conditions",
        roles=ONLY_UW,
        takes_body=True,
        body={"text": "Obtain a written explanation", "priority": "attention"},
    ),
    ep(
        "PATCH",
        f"{C}/underwriting-report/latest/conditions/{{condition_id}}",
        roles=ONLY_UW,
        takes_body=True,
        body={"decision": "accepted"},
    ),
    ep("POST", f"{C}/underwriting-report/latest/sign-off", roles=ONLY_UW, takes_body=True, body={}),
    # hardship
    ep("POST", f"{C}/hardship-assessment"),
    ep("GET", f"{C}/hardship-assessment/latest"),
    ep(
        "PUT",
        f"{C}/hardship-assessment/latest/confirmations",
        roles=ONLY_LM,
        takes_body=True,
        body={"intent": {}},
    ),
    ep(
        "PATCH",
        f"{C}/hardship-assessment/latest/budget/{{line_id}}",
        roles=ONLY_LM,
        takes_body=True,
        body={"adjusted_amount": "1.00", "reason": "one-off"},
    ),
    # loss mitigation recommendation
    ep("POST", f"{C}/lm-recommendation", roles=ONLY_LM),
    ep("GET", f"{C}/lm-recommendation/latest"),
    ep(
        "PUT",
        f"{C}/lm-recommendation/latest/conditions/{{condition_id}}/override",
        roles=ONLY_LM,
        takes_body=True,
        body={"status": "met", "reason": "checked"},
    ),
    ep("POST", f"{C}/lm-recommendation/latest/sign-off", roles=ONLY_LM, takes_body=True, body={}),
    # audit, guidelines, jobs
    ep("GET", f"{C}/audit"),
    ep("GET", "/api/v1/guidelines/sources", special="no case"),
    ep("GET", "/api/v1/guidelines/passages/{passage_id}", special="no case"),
    ep("POST", "/api/v1/guidelines/ask", takes_body=True, special="no case; a model call"),
    ep(
        "POST",
        "/api/v1/guidelines/answers/{answer_id}/feedback",
        takes_body=True,
        special="no case; an answer",
    ),
    ep("GET", "/api/v1/jobs/{job_id}", special="a job, not a case"),
)
BY_KEY = {e.key: e for e in ENDPOINTS}
CASE_ENDPOINTS = [e for e in ENDPOINTS if e.is_case and not e.special]


def url(endpoint: Endpoint, case: uuid.UUID | str = DANIEL) -> str:
    """The path with every parameter filled in: the case asked for, a name that exists for the
    fixed ones, and a random id (which names nothing) for the rest."""
    fixed = {
        "case_id": str(case),
        "field_name": "net_pay_current",
        "page": "1",
        "item_id": "pay_stubs_30_days",
        "passage_id": "sample-investor-a-v1.order.1",
    }
    names = re.findall(r"{(\w+)}", endpoint.path)
    return endpoint.path.format(**{n: fixed.get(n, str(uuid.uuid4())) for n in names})


def headers(role: Role) -> dict[str, str]:
    return auth_headers(role)


async def call(
    client: httpx.AsyncClient,
    endpoint: Endpoint,
    *,
    role: Role | None,
    case: uuid.UUID | str = DANIEL,
    body: dict[str, Any] | None = None,
) -> httpx.Response:
    return await client.request(
        endpoint.method,
        url(endpoint, case),
        headers=headers(role) if role else {},
        json=body if endpoint.method in {"POST", "PUT", "PATCH"} else None,
    )


@pytest.fixture(autouse=True)
async def seeded(session: AsyncSession) -> None:
    await seed(session, "demo-pass")


# --- the table is the whole API --------------------------------------------------------------


def served() -> set[tuple[str, str]]:
    found: set[tuple[str, str]] = set()
    for path, item in app.openapi()["paths"].items():
        for method in item:
            if method in {"get", "post", "put", "patch", "delete"}:
                found.add((method.upper(), path))
    return found


def test_the_table_is_every_operation_the_app_serves() -> None:
    assert set(BY_KEY) == served()
    assert len(ENDPOINTS) == len(BY_KEY)  # no operation listed twice


# --- 401: no token ---------------------------------------------------------------------------


@pytest.mark.parametrize("endpoint", [e for e in ENDPOINTS if not e.anonymous], ids=str)
async def test_no_token_is_a_401(client: httpx.AsyncClient, endpoint: Endpoint) -> None:
    response = await call(client, endpoint, role=None, body=endpoint.body or {})

    assert response.status_code == 401, (endpoint.key, response.text)


@pytest.mark.parametrize("endpoint", [e for e in ENDPOINTS if not e.anonymous][:6], ids=str)
async def test_a_token_that_is_not_one_is_a_401(
    client: httpx.AsyncClient, endpoint: Endpoint
) -> None:
    response = await client.request(
        endpoint.method, url(endpoint), headers={"Authorization": "Bearer not-a-token"}
    )

    assert response.status_code == 401


# --- 403: a role that may not act ------------------------------------------------------------


@pytest.mark.parametrize("endpoint", [e for e in CASE_ENDPOINTS if e.roles != ANY], ids=str)
async def test_a_role_that_may_not_act_is_a_403_and_the_admin_is_one_of_them(
    client: httpx.AsyncClient, endpoint: Endpoint
) -> None:
    case = DANIEL if endpoint.roles == ONLY_UW else ANGELA
    for role in sorted(ANY - endpoint.roles, key=str):
        response = await call(client, endpoint, role=role, case=case, body=endpoint.body or {})

        assert response.status_code == 403, (endpoint.key, role, response.text)
        assert response.json()["code"] == "forbidden"
    assert Role.ADMIN not in endpoint.roles


# --- 404: a case the role may not see --------------------------------------------------------


def hidden_pairs(endpoint: Endpoint) -> list[tuple[Role, uuid.UUID]]:
    """(role, case) pairs where the role passes the gate but the case is the other pillar's."""
    pairs = [(Role.UNDERWRITER, ANGELA), (Role.LM_SPECIALIST, DANIEL)]
    return [(role, case) for role, case in pairs if role in endpoint.roles]


@pytest.mark.parametrize("endpoint", CASE_ENDPOINTS, ids=str)
async def test_the_other_pillars_case_is_a_404_that_says_case_not_found(
    client: httpx.AsyncClient, endpoint: Endpoint
) -> None:
    pairs = hidden_pairs(endpoint)
    assert pairs, endpoint.key
    for role, case in pairs:
        response = await call(client, endpoint, role=role, case=case, body=endpoint.body or {})

        assert response.status_code == 404, (endpoint.key, role, response.text)
        assert response.json() == {"code": "not_found", "message": "Case not found"}


@pytest.mark.parametrize("endpoint", CASE_ENDPOINTS, ids=str)
async def test_a_case_id_that_is_not_one_is_a_404_not_a_500(
    client: httpx.AsyncClient, endpoint: Endpoint
) -> None:
    role = sorted(endpoint.roles, key=str)[0] if endpoint.roles != ANY else Role.UNDERWRITER
    for nonsense in ("nope", str(uuid.uuid4())):
        response = await call(client, endpoint, role=role, case=nonsense, body=endpoint.body or {})

        assert response.status_code == 404, (endpoint.key, nonsense, response.text)


# --- 422: a body that is not valid ------------------------------------------------------------


@pytest.mark.parametrize("endpoint", [e for e in CASE_ENDPOINTS if e.takes_body], ids=str)
async def test_a_body_no_schema_accepts_is_a_422(
    client: httpx.AsyncClient, endpoint: Endpoint
) -> None:
    role, case = (
        (Role.LM_SPECIALIST, ANGELA) if endpoint.roles == ONLY_LM else (Role.UNDERWRITER, DANIEL)
    )

    response = await call(client, endpoint, role=role, case=case, body=NONSENSE)

    assert response.status_code == 422, (endpoint.key, response.text)
    assert response.json()["code"] == "validation_failed"


async def test_an_upload_with_no_files_is_a_422_and_another_pillars_case_is_a_404(
    docs_client: httpx.AsyncClient,
) -> None:
    empty = await docs_client.post(
        f"/api/v1/cases/{DANIEL}/documents", headers=headers(Role.UNDERWRITER)
    )
    hidden = await upload(
        docs_client, ANGELA, [("a.pdf", b"%PDF-1.4\n%%EOF")], role=Role.UNDERWRITER
    )

    assert empty.status_code == 422
    assert (hidden.status_code, hidden.json()["message"]) == (404, "Case not found")


# --- the success case of each endpoint is tested somewhere -----------------------------------

TESTS = Path(__file__).resolve().parent


def literals(path: str) -> list[str]:
    """The fixed words of a path: ``["lm-recommendation", "latest", "conditions", "override"]``."""
    parts = [p for p in path.split("/") if p and not p.startswith("{") and p not in {"api", "v1"}]
    return [p for p in parts if p != "cases"]


def test_every_endpoint_has_a_success_test_that_names_its_path() -> None:
    sources = {
        f.name: f.read_text(encoding="utf-8")
        for f in TESTS.glob("test_*.py")
        if f.name not in {"test_endpoint_matrix.py"}
    }
    missing: list[str] = []
    for endpoint in ENDPOINTS:
        words = literals(endpoint.path)
        if not words:  # "/cases" and "/health" are named in full below
            words = [endpoint.path.rsplit("/", 1)[-1]]
        needle = words[-1]
        first = words[0]
        found = any(needle in text and first in text for text in sources.values())
        if not found:
            missing.append(f"{endpoint.method} {endpoint.path}")
    assert missing == []

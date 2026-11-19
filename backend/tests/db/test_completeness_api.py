"""Completeness through the API and Postgres: Daniel Reyes's gaps, overrides, and who may ask.

Daniel's pay stubs cover 14 of 30 days, his 2024 W-2 and return are absent, his August statement
is incomplete (a page is missing), and his credit report has no date read, so the overall status is
incomplete. An override needs a written reason, counts as satisfied, keeps the computed status
beside it, and is audited.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta
from typing import Any

import httpx
import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.enums import Certainty, DocumentStatus, FlagSeverity, Role
from app.db.models import Document, ExtractionRun, Flag
from app.db.models import Field as FieldRow
from app.db.seed import case_id, seed
from app.services.document_config import get_document_fields
from app.services.normalize import normalize, stored_text
from tests.db.conftest import FakeQueue, auth_headers

DANIEL = case_id("Daniel Reyes — purchase")  # underwriting
ANGELA = case_id("Angela Whitfield — hardship")  # loss mitigation
FIELDS = get_document_fields()
BASE_TIME = datetime(2026, 10, 12, tzinfo=UTC)
WAGE = "pillar1-wage-earner@1"
HARDSHIP = "pillar2-hardship@1"
PROFILE = {
    "borrower_names": ["Daniel Reyes"],
    "employment_type": "wage_earner",
    "reference_date": "2026-10-12",
}


@pytest.fixture(autouse=True)
async def seeded(session: AsyncSession) -> None:
    await seed(session, "demo-pass")


def headers(role: Role = Role.UNDERWRITER) -> dict[str, str]:
    return auth_headers(role)


def url(case: uuid.UUID = DANIEL, tail: str = "") -> str:
    return f"/api/v1/cases/{case}/completeness{tail}"


async def set_profile(
    client: httpx.AsyncClient,
    case: uuid.UUID = DANIEL,
    body: dict[str, Any] | None = None,
    role: Role = Role.UNDERWRITER,
) -> None:
    response = await client.put(
        f"/api/v1/cases/{case}/profile", json=body or PROFILE, headers=headers(role)
    )
    assert response.status_code == 200, response.text


async def seed_document(
    session: AsyncSession,
    case: uuid.UUID,
    doc_type: str,
    *,
    borrower: str | None = "Daniel Reyes",
    start: str | None = None,
    end: str | None = None,
    values: dict[str, str] | None = None,
    flags: tuple[str, ...] = (),
    status: DocumentStatus = DocumentStatus.NEEDS_REVIEW,
    minutes: int = 0,
) -> uuid.UUID:
    document = Document(
        case_id=case,
        file_name=f"{doc_type}.pdf",
        s3_key=f"k/{uuid.uuid4().hex}",
        sha256=uuid.uuid4().hex * 2,
        mime="application/pdf",
        size_bytes=1,
        status=status,
        doc_type=doc_type,
        borrower=borrower,
        period_start=date.fromisoformat(start) if start else None,
        period_end=date.fromisoformat(end) if end else None,
        created_at=BASE_TIME + timedelta(minutes=minutes),
    )
    session.add(document)
    await session.flush()
    run = ExtractionRun(document_id=document.id, doc_type=doc_type, active=True, provider="fake")
    session.add(run)
    await session.flush()
    for number, (name, value) in enumerate((values or {}).items(), start=1):
        kind = FIELDS.kind_of(doc_type, name)
        normalized = normalize(kind, stored_text(kind, value))
        session.add(
            FieldRow(
                document_id=document.id,
                run_id=run.id,
                name=name,
                value=stored_text(kind, value),
                normalized_value=normalized,
                original_value=normalized,
                certainty=Certainty.HIGH,
                line_refs=[f"p1-L{number}"],
            )
        )
    for code in flags:
        session.add(
            Flag(
                case_id=case,
                feature="documents",
                entity_type="document",
                entity_id=document.id,
                code=code,
                severity=FlagSeverity.WARNING,
                message="m",
            )
        )
    await session.flush()
    return document.id


async def seed_daniel(session: AsyncSession) -> dict[str, uuid.UUID]:
    return {
        "stub": await seed_document(
            session, DANIEL, "pay_stub", start="2026-09-14", end="2026-09-27"
        ),
        "august": await seed_document(
            session,
            DANIEL,
            "bank_statement",
            start="2026-08-01",
            end="2026-08-31",
            values={"account_last4": "6032"},
            flags=("DI-W701",),  # "Page 1 of 3" with two pages uploaded
            minutes=1,
        ),
        "september": await seed_document(
            session,
            DANIEL,
            "bank_statement",
            start="2026-09-01",
            end="2026-09-30",
            values={"account_last4": "6032"},
            minutes=2,
        ),
        "w2": await seed_document(session, DANIEL, "w2", values={"tax_year": "2025"}, minutes=3),
        "return": await seed_document(
            session, DANIEL, "tax_return_1040", values={"tax_year": "2025"}, minutes=4
        ),
        "credit": await seed_document(session, DANIEL, "credit_report", minutes=5),
    }


async def run(
    client: httpx.AsyncClient,
    checklist: str = WAGE,
    case: uuid.UUID = DANIEL,
    role: Role = Role.UNDERWRITER,
) -> httpx.Response:
    return await client.post(url(case), json={"checklist_id": checklist}, headers=headers(role))


def item(result: dict[str, Any], item_id: str) -> dict[str, Any]:
    return next(i for i in result["items"] if i["item_id"] == item_id)


async def rows(session: AsyncSession, sql: str, **params: Any) -> list[Any]:
    return list((await session.execute(sa.text(sql), params)).all())


# --- Daniel Reyes ---------------------------------------------------------------------------


async def test_daniels_case_is_incomplete_with_the_gaps_the_feature_design_names(
    docs_client: httpx.AsyncClient, session: AsyncSession
) -> None:
    ids = await seed_daniel(session)
    await set_profile(docs_client)

    response = await run(docs_client)

    assert response.status_code == 200, response.text
    result = response.json()
    assert result["case_id"] == str(DANIEL) and result["overall_status"] == "incomplete"
    assert (result["checklist_id"], result["checklist_version"], result["checklist_label"]) == (
        WAGE,
        "1",
        "illustrative",
    )
    assert result["run_at"] and result["id"]

    stubs = item(result, "pay_stubs_30_days")
    assert (stubs["status"], stubs["reason"]) == ("partial", "14 of 30 days of pay stubs found")
    assert stubs["document_ids"] == [str(ids["stub"])]
    assert item(result, "w2_two_years")["reason"] == "W-2s found for 2025; missing 2024"
    assert item(result, "tax_returns_two_years")["reason"] == (
        "Tax returns found for 2025; missing 2024"
    )
    banks = item(result, "bank_statements_2_months")
    assert banks["status"] == "partial" and "a document is incomplete" in banks["reason"]
    assert set(banks["document_ids"]) == {str(ids["august"]), str(ids["september"])}
    credit = item(result, "credit_report_120_days")
    # The contract has no "needs review" status yet, so the reason says it.
    assert credit["status"] == "partial"
    assert credit["reason"] == "Needs review: Credit report: the date of the document was not read"
    assert len(result["outstanding"]) == 5
    assert (
        result["outstanding"][0] == "Pay stubs covering 30 days: 14 of 30 days of pay stubs found"
    )


async def test_the_latest_result_is_the_last_run_and_there_is_none_before_a_run(
    docs_client: httpx.AsyncClient, session: AsyncSession
) -> None:
    await seed_daniel(session)
    await set_profile(docs_client)
    before = await docs_client.get(url(tail="/latest"), headers=headers())
    assert before.status_code == 404 and before.json()["code"] == "not_found"

    first = (await run(docs_client)).json()
    latest = await docs_client.get(url(tail="/latest"), headers=headers())
    assert latest.status_code == 200 and latest.json() == first


async def test_the_stored_result_keeps_its_run_and_the_settings_it_used(
    docs_client: httpx.AsyncClient, session: AsyncSession, fake_queue: FakeQueue
) -> None:
    await seed_daniel(session)
    await set_profile(docs_client)
    await run(docs_client)

    stored = (
        await rows(
            session,
            "SELECT r.feature, r.status, r.job_id, r.config_versions, c.overall_status "
            "FROM analysis_runs r JOIN completeness_results c ON c.run_id = r.id",
        )
    )[0]
    assert (stored.feature, stored.status, stored.job_id, stored.overall_status) == (
        "completeness",
        "succeeded",
        None,  # it is answered in the request: no job
        "incomplete",
    )
    assert stored.config_versions["checklist"]["name"] == WAGE
    assert stored.config_versions["checklist"]["version"] == "2026-11-19.1"
    assert fake_queue.calls == []
    assert [
        tuple(v) for v in await rows(session, "SELECT kind, name, label FROM config_versions")
    ] == [("checklist", WAGE, "illustrative")]
    event = (
        await rows(
            session,
            "SELECT action, role, after FROM audit_events WHERE action = 'completeness.run'",
        )
    )[0]
    assert (event.action, event.role) == ("completeness.run", "underwriter")
    assert event.after["overall"] == "incomplete" and event.after["items"] == {
        "partial": 4,
        "needs_review": 1,
    }


async def test_a_complete_case_is_complete_and_a_needs_review_item_alone_is_not_complete(
    docs_client: httpx.AsyncClient, session: AsyncSession
) -> None:
    await set_profile(docs_client)
    await seed_document(session, DANIEL, "pay_stub", start="2026-08-31", end="2026-10-04")
    for start, end in (("2026-08-01", "2026-08-31"), ("2026-09-01", "2026-09-30")):
        await seed_document(
            session,
            DANIEL,
            "bank_statement",
            start=start,
            end=end,
            values={"account_last4": "6032"},
        )
    for year in ("2025", "2024"):
        await seed_document(session, DANIEL, "w2", values={"tax_year": year})
        await seed_document(session, DANIEL, "tax_return_1040", values={"tax_year": year})
    credit_id = await seed_document(session, DANIEL, "credit_report")  # no date read yet

    result = (await run(docs_client)).json()
    assert [i["status"] for i in result["items"]][:4] == ["satisfied"] * 4
    # Only a needs-review item is left: the FSD calls that "needs review", the contract says
    # incomplete, and the stored status keeps the difference.
    assert result["overall_status"] == "incomplete"
    stored = (await rows(session, "SELECT overall_status FROM completeness_results"))[0]
    assert stored.overall_status == "needs_review"

    await session.execute(
        sa.text("UPDATE documents SET status = 'failed' WHERE id = :d"), {"d": credit_id}
    )
    assert (await run(docs_client)).json()["items"][4]["status"] == "missing"  # a failed read


async def test_a_dated_credit_report_within_120_days_completes_the_checklist(
    docs_client: httpx.AsyncClient, session: AsyncSession
) -> None:
    await set_profile(docs_client)
    await seed_document(session, DANIEL, "pay_stub", start="2026-08-31", end="2026-10-04")
    for start, end in (("2026-08-01", "2026-08-31"), ("2026-09-01", "2026-09-30")):
        await seed_document(
            session,
            DANIEL,
            "bank_statement",
            start=start,
            end=end,
            values={"account_last4": "6032"},
        )
    for year in ("2025", "2024"):
        await seed_document(session, DANIEL, "w2", values={"tax_year": year})
        await seed_document(session, DANIEL, "tax_return_1040", values={"tax_year": year})
    await seed_document(session, DANIEL, "credit_report", values={"report_date": "2026-10-12"})

    result = (await run(docs_client)).json()
    assert result["overall_status"] == "complete" and result["outstanding"] == []
    assert {i["status"] for i in result["items"]} == {"satisfied"}


# --- overrides ------------------------------------------------------------------------------


async def test_an_override_needs_a_reason_counts_as_satisfied_and_keeps_the_computed_status(
    docs_client: httpx.AsyncClient, session: AsyncSession
) -> None:
    await seed_daniel(session)
    await set_profile(docs_client)
    await run(docs_client)
    patch = f"{url(tail='/latest/items/w2_two_years')}"

    response = await docs_client.patch(
        patch,
        json={"action": "override", "reason": "The 2024 W-2 was never issued"},
        headers=headers(),
    )

    assert response.status_code == 200, response.text
    result = response.json()
    w2s = item(result, "w2_two_years")
    assert w2s["status"] == "overridden"
    assert w2s["override_reason"] == "The 2024 W-2 was never issued"
    assert w2s["reason"] == "W-2s found for 2025; missing 2024"  # what code found is still shown
    assert not any(line.startswith("W-2s") for line in result["outstanding"])
    assert result["overall_status"] == "incomplete"  # four items are still open

    stored = (await rows(session, "SELECT items, updated_by FROM completeness_results"))[0]
    kept = next(i for i in stored.items if i["item_id"] == "w2_two_years")
    assert kept["status"] == "partial"  # the computed status was not overwritten
    assert kept["override"]["reason"] == "The 2024 W-2 was never issued"
    assert kept["override"]["by"] and kept["override"]["at"] and stored.updated_by is not None
    event = (
        await rows(
            session,
            "SELECT action, before, after, reason FROM audit_events "
            "WHERE action = 'completeness.item_overridden'",
        )
    )[0]
    assert event.reason == "The 2024 W-2 was never issued"
    assert event.before["computed_status"] == "partial" and event.before["override"] is None
    assert event.after["override"]["reason"] == "The 2024 W-2 was never issued"


async def test_overriding_every_open_item_completes_the_checklist_and_clearing_reopens_it(
    docs_client: httpx.AsyncClient, session: AsyncSession
) -> None:
    await seed_daniel(session)
    await set_profile(docs_client)
    result = (await run(docs_client)).json()
    for entry in result["items"]:
        response = await docs_client.patch(
            url(tail=f"/latest/items/{entry['item_id']}"),
            json={"action": "override", "reason": "Reviewed with the borrower"},
            headers=headers(),
        )
        assert response.status_code == 200
    done = response.json()
    assert done["overall_status"] == "complete" and done["outstanding"] == []
    assert {i["status"] for i in done["items"]} == {"overridden"}

    cleared = await docs_client.patch(
        url(tail="/latest/items/pay_stubs_30_days"), json={"action": "clear"}, headers=headers()
    )
    body = cleared.json()
    assert cleared.status_code == 200 and body["overall_status"] == "incomplete"
    stubs = item(body, "pay_stubs_30_days")
    assert (stubs["status"], stubs["override_reason"]) == ("partial", None)
    assert body["outstanding"] == ["Pay stubs covering 30 days: 14 of 30 days of pay stubs found"]
    actions = [
        r.action
        for r in await rows(
            session,
            "SELECT action FROM audit_events WHERE action LIKE 'completeness.%' ORDER BY id",
        )
    ]
    assert actions == ["completeness.run"] + ["completeness.item_overridden"] * 5 + [
        "completeness.override_cleared"
    ]


@pytest.mark.parametrize(
    "body",
    [
        {"action": "override"},
        {"action": "override", "reason": ""},
        {"action": "override", "reason": "   "},
        {"action": "override", "reason": "x" * 501},
        {"action": "approve", "reason": "ok"},
        {"reason": "no action"},
        {"action": "override", "reason": "ok", "status": "satisfied"},  # the status is not editable
    ],
)
async def test_a_bad_override_request_changes_nothing(
    docs_client: httpx.AsyncClient, session: AsyncSession, body: dict[str, Any]
) -> None:
    await seed_daniel(session)
    await set_profile(docs_client)
    await run(docs_client)
    response = await docs_client.patch(
        url(tail="/latest/items/w2_two_years"), json=body, headers=headers()
    )
    assert response.status_code == 422
    assert (
        await rows(session, "SELECT 1 FROM audit_events WHERE action LIKE 'completeness.item%'")
        == []
    )


async def test_an_override_the_item_cannot_take_is_a_409_or_a_404(
    docs_client: httpx.AsyncClient, session: AsyncSession
) -> None:
    await set_profile(docs_client)
    await seed_document(session, DANIEL, "pay_stub", start="2026-09-01", end="2026-09-30")
    await run(docs_client)
    override = {"action": "override", "reason": "ok"}

    satisfied = await docs_client.patch(
        url(tail="/latest/items/pay_stubs_30_days"), json=override, headers=headers()
    )
    assert satisfied.status_code == 409 and satisfied.json()["code"] == "nothing_to_override"
    none_to_clear = await docs_client.patch(
        url(tail="/latest/items/w2_two_years"), json={"action": "clear"}, headers=headers()
    )
    assert none_to_clear.status_code == 409 and none_to_clear.json()["code"] == "no_override"
    await docs_client.patch(
        url(tail="/latest/items/w2_two_years"), json=override, headers=headers()
    )
    twice = await docs_client.patch(
        url(tail="/latest/items/w2_two_years"), json=override, headers=headers()
    )
    assert twice.status_code == 409 and twice.json()["code"] == "already_overridden"
    unknown = await docs_client.patch(
        url(tail="/latest/items/not_an_item"), json=override, headers=headers()
    )
    assert unknown.status_code == 404


async def test_overriding_before_any_run_is_a_404(docs_client: httpx.AsyncClient) -> None:
    response = await docs_client.patch(
        url(tail="/latest/items/w2_two_years"),
        json={"action": "override", "reason": "ok"},
        headers=headers(),
    )
    assert response.status_code == 404


async def test_a_new_run_starts_without_the_old_overrides_and_the_old_result_is_kept(
    docs_client: httpx.AsyncClient, session: AsyncSession
) -> None:
    await seed_daniel(session)
    await set_profile(docs_client)
    await run(docs_client)
    await docs_client.patch(
        url(tail="/latest/items/w2_two_years"),
        json={"action": "override", "reason": "ok"},
        headers=headers(),
    )
    second = (await run(docs_client)).json()
    assert item(second, "w2_two_years")["status"] == "partial"  # a fresh check, not the override
    assert len(await rows(session, "SELECT 1 FROM completeness_results")) == 2
    older = await rows(session, "SELECT items FROM completeness_results ORDER BY created_at, id")
    assert any(i.get("override") for r in older for i in r.items)  # the first result still has it


# --- what it cannot run on ------------------------------------------------------------------


async def test_the_profile_must_be_entered_first(docs_client: httpx.AsyncClient) -> None:
    response = await run(docs_client)
    assert response.status_code == 422 and response.json()["code"] == "profile_required"


async def test_an_unknown_checklist_or_one_for_the_other_pillar_is_a_422(
    docs_client: httpx.AsyncClient,
) -> None:
    await set_profile(docs_client)
    unknown = await run(docs_client, "nothing@1")
    assert unknown.status_code == 422 and unknown.json()["code"] == "unknown_checklist"
    wrong = await run(docs_client, HARDSHIP)  # Daniel's case is an underwriting case
    assert wrong.status_code == 422 and wrong.json()["code"] == "wrong_checklist"


async def test_a_checklist_for_wage_earners_is_not_run_for_a_self_employed_borrower(
    docs_client: httpx.AsyncClient,
) -> None:
    await set_profile(docs_client, body={**PROFILE, "employment_type": "self_employed"})
    response = await run(docs_client)
    assert response.status_code == 422 and response.json()["code"] == "wrong_checklist"


@pytest.mark.parametrize("body", [{}, {"checklist_id": ""}, {"checklist_id": WAGE, "x": 1}])
async def test_the_request_needs_exactly_a_checklist_id(
    docs_client: httpx.AsyncClient, body: dict[str, Any]
) -> None:
    await set_profile(docs_client)
    assert (await docs_client.post(url(), json=body, headers=headers())).status_code == 422


async def test_the_hardship_checklist_runs_for_a_loss_mitigation_case(
    docs_client: httpx.AsyncClient, session: AsyncSession
) -> None:
    profile = {
        "borrower_names": ["Angela Whitfield"],
        "employment_type": "wage_earner",
        "reference_date": "2026-10-12",
    }
    await set_profile(docs_client, ANGELA, profile, Role.LM_SPECIALIST)
    await seed_document(
        session,
        ANGELA,
        "mortgage_assistance_application",
        borrower="Angela Whitfield",
        values={"signed_date": "2026-10-01"},
    )
    await seed_document(session, ANGELA, "hardship_letter", borrower="Angela Whitfield")
    await seed_document(
        session,
        ANGELA,
        "bank_statement",
        borrower="Angela Whitfield",
        start="2026-07-01",
        end="2026-07-31",
        values={"account_last4": "1234"},
    )
    await seed_document(
        session,
        ANGELA,
        "bank_statement",
        borrower="Angela Whitfield",
        start="2026-09-01",
        end="2026-09-30",
        values={"account_last4": "1234"},
    )

    result = (await run(docs_client, HARDSHIP, ANGELA, Role.LM_SPECIALIST)).json()

    assert result["checklist_id"] == HARDSHIP and result["overall_status"] == "incomplete"
    assert item(result, "signed_application")["status"] == "satisfied"
    assert item(result, "hardship_letter")["status"] == "satisfied"
    assert item(result, "pay_stubs_30_days")["status"] == "missing"
    # July and September, no August: neither month alone covers two.
    assert item(result, "bank_statements_2_months")["reason"] == (
        "1 of 2 months of bank statements found for the account ending 1234"
    )


async def test_only_this_cases_documents_and_borrowers_count(
    docs_client: httpx.AsyncClient, session: AsyncSession
) -> None:
    await set_profile(docs_client)
    await seed_document(session, ANGELA, "pay_stub", start="2026-09-01", end="2026-09-30")
    await seed_document(
        session, DANIEL, "pay_stub", borrower="Maria Lopez", start="2026-09-01", end="2026-09-30"
    )
    result = (await run(docs_client)).json()
    assert item(result, "pay_stubs_30_days")["status"] == "missing"


# --- who may ask ----------------------------------------------------------------------------


async def test_a_case_the_caller_cannot_see_is_a_404_on_every_endpoint(
    docs_client: httpx.AsyncClient, session: AsyncSession
) -> None:
    await seed_daniel(session)
    await set_profile(docs_client)
    await run(docs_client)
    lm = headers(Role.LM_SPECIALIST)  # Daniel's case is a Pillar 1 case

    post = await docs_client.post(url(), json={"checklist_id": WAGE}, headers=lm)
    assert post.status_code == 404
    assert (await docs_client.get(url(tail="/latest"), headers=lm)).status_code == 404
    patch = await docs_client.patch(
        url(tail="/latest/items/w2_two_years"),
        json={"action": "override", "reason": "ok"},
        headers=lm,
    )
    assert patch.status_code == 404


async def test_the_admin_sees_both_pillars_and_no_token_is_a_401(
    docs_client: httpx.AsyncClient, session: AsyncSession
) -> None:
    await seed_daniel(session)
    await set_profile(docs_client)
    await run(docs_client)
    assert (
        await docs_client.get(url(tail="/latest"), headers=headers(Role.ADMIN))
    ).status_code == 200
    assert (await docs_client.get(url(tail="/latest"))).status_code == 401
    assert (await docs_client.post(url(), json={"checklist_id": WAGE})).status_code == 401
    patch = await docs_client.patch(url(tail="/latest/items/x"), json={"action": "clear"})
    assert patch.status_code == 401
    assert (
        await docs_client.get("/api/v1/cases/nope/completeness/latest", headers=headers())
    ).status_code == 404

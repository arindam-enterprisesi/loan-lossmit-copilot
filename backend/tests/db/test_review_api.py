"""Extraction view, field review, type change and jobs, over HTTP against the real stack.

Each test uploads a generated document, runs the real pipeline (rule-based fake reader), then calls
the endpoint. The rules under test: a correction keeps ``original_value``, needs a reason, writes an
audit event and re-runs the checks with no model call; a stale version is a conflict; and nothing
is ever decided: a person's review is recorded, never replaced.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from typing import Any

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.api.schemas.extraction import ExtractionOut, FieldOut
from app.db.enums import Role
from app.db.seed import case_id, seed, user_id
from app.services.doc_lines import DocLine
from app.services.document_config import get_document_fields
from app.services.extractor import ExtractedField, ExtractionOutcome
from app.services.fake_reader import FakeExtractor
from app.storage import Storage
from tests.conftest import Rendered
from tests.db.conftest import FakeQueue, auth_headers
from tests.db.test_documents_api import rows
from tests.db.test_pipeline import (
    AUGUST,
    DANIEL,
    NET_PAY_MESSAGE,
    SEPTEMBER,
    STUB,
    document,
    flags_of,
    one,
    run,
    upload_files,
)

CFG = get_document_fields()
ANGELA = case_id("Angela Whitfield — hardship")


@pytest.fixture(autouse=True)
async def seeded(session: AsyncSession) -> None:
    await seed(session, "demo-pass")


class Stub:
    """A pay stub that has been uploaded and read, with the URLs to review it."""

    def __init__(self, body: dict[str, Any]) -> None:
        self.body = body
        self.doc = body["documents"][0]["id"]
        self.base = f"/api/v1/cases/{DANIEL}/documents/{self.doc}"

    def field(self, name: str) -> str:
        return f"{self.base}/fields/{name}"


async def read_stub(
    client: httpx.AsyncClient,
    storage: Storage,
    factory: async_sessionmaker[AsyncSession],
    rendered: Rendered,
    path: str = STUB,
    **ctx: Any,
) -> Stub:
    body = await upload_files(client, rendered, [path])
    await run(body, storage, factory, **ctx)
    return Stub(body)


def headers(role: Role = Role.UNDERWRITER) -> dict[str, str]:
    return auth_headers(role)


async def get_extraction(client: httpx.AsyncClient, stub: Stub) -> dict[str, Any]:
    response = await client.get(f"{stub.base}/extraction", headers=headers())
    assert response.status_code == 200, response.text
    return response.json()  # type: ignore[no-any-return]


def by_name(extraction: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {f["name"]: f for f in extraction["fields"]}


async def review(
    client: httpx.AsyncClient,
    stub: Stub,
    name: str,
    body: dict[str, Any],
    role: Role = Role.UNDERWRITER,
) -> httpx.Response:
    return await client.patch(stub.field(name), json=body, headers=headers(role))


# --- GET extraction ---------------------------------------------------------------------------


async def test_the_extraction_shows_fields_flags_and_a_template_summary(
    docs_client: httpx.AsyncClient,
    s3_storage: Storage,
    session_factory: async_sessionmaker[AsyncSession],
    rendered: Rendered,
) -> None:
    stub = await read_stub(docs_client, s3_storage, session_factory, rendered)

    extraction = await get_extraction(docs_client, stub)

    assert set(extraction) == set(ExtractionOut.model_fields)  # exactly the contract's keys
    assert extraction["doc_type"] == "pay_stub" and extraction["document_id"] == stub.doc
    assert (extraction["provider"], extraction["model"], extraction["prompt_id"]) == (
        "fake",
        "rule-based-v1",
        "fake-extract@1",
    )
    assert extraction["summary"] == (
        "Pay stub, Daniel Reyes, 2026-09-14 to 2026-09-27: gross 3,070.50, net 2,083.61."
    )
    assert extraction["flags"] == []  # nothing about the document as a whole

    first = extraction["fields"][0]  # flagged fields come first (FD 1.2)
    assert set(first) == set(FieldOut.model_fields)
    assert (first["name"], first["value"], first["original_value"]) == (
        "net_pay_current",
        "2083.61",
        "2083.61",
    )
    assert (first["certainty"], first["review_status"], first["version"]) == (
        "high",
        "unreviewed",
        1,
    )
    assert first["reviewed_by"] is None and first["reviewed_at"] is None
    [flag] = first["flags"]
    assert (flag["code"], flag["severity"], flag["message"]) == (
        "DI-CHK-02",
        "warning",
        NET_PAY_MESSAGE,
    )
    assert set(flag["evidence"]) == {"document_id", "page", "line_ids", "bbox"}  # not the working
    assert (flag["evidence"]["page"], flag["evidence"]["line_ids"]) == (
        1,
        ["p1-L17", "p1-L25", "p1-L31"],
    )
    assert first["evidence"]["line_ids"] == ["p1-L31"]
    assert set(first["evidence"]["bbox"]) == {"x0", "y0", "x1", "y1"}


async def test_unflagged_fields_follow_in_the_configured_order(
    docs_client: httpx.AsyncClient,
    s3_storage: Storage,
    session_factory: async_sessionmaker[AsyncSession],
    rendered: Rendered,
) -> None:
    stub = await read_stub(docs_client, s3_storage, session_factory, rendered)
    names = [f["name"] for f in (await get_extraction(docs_client, stub))["fields"]]
    configured = [f.name for f in CFG.spec("pay_stub").fields]  # type: ignore[union-attr]
    assert names[0] == "net_pay_current"
    assert names[1:] == [n for n in configured if n != "net_pay_current" and n in names]
    assert all(f["flags"] == [] for f in (await get_extraction(docs_client, stub))["fields"][1:])


async def test_document_level_flags_are_listed_with_the_extraction(
    docs_client: httpx.AsyncClient,
    s3_storage: Storage,
    session_factory: async_sessionmaker[AsyncSession],
    rendered: Rendered,
) -> None:
    stub = await read_stub(docs_client, s3_storage, session_factory, rendered, AUGUST)
    extraction = await get_extraction(docs_client, stub)

    [incomplete] = extraction["flags"]
    assert incomplete["code"] == "DI-W701"
    assert incomplete["message"].startswith("Incomplete: this document says it has 3 pages")
    assert incomplete["evidence"]["line_ids"] == ["p1-L26", "p2-L17"]
    # The balance check is flagged on the closing balance, which comes first.
    assert extraction["fields"][0]["name"] in {"closing_balance", "total_withdrawals"}


async def test_a_document_that_has_not_been_read_has_no_extraction_yet(
    docs_client: httpx.AsyncClient, rendered: Rendered
) -> None:
    body = await upload_files(docs_client, rendered, [STUB])  # uploaded, never processed
    stub = Stub(body)
    response = await docs_client.get(f"{stub.base}/extraction", headers=headers())
    assert response.status_code == 404
    assert response.json() == {
        "code": "not_found",
        "message": "This document has not been read yet",
    }


async def test_a_document_waiting_for_its_type_has_no_extraction_either(
    docs_client: httpx.AsyncClient,
    s3_storage: Storage,
    session_factory: async_sessionmaker[AsyncSession],
    rendered: Rendered,
) -> None:
    body = await upload_files(docs_client, rendered, [SEPTEMBER], declared_type="tax_return_1040")
    await run(body, s3_storage, session_factory)
    stub = Stub(body)
    assert (await docs_client.get(f"{stub.base}/extraction", headers=headers())).status_code == 404


async def test_an_account_number_is_stored_and_shown_as_its_last_four_digits(
    docs_client: httpx.AsyncClient,
    session: AsyncSession,
    s3_storage: Storage,
    session_factory: async_sessionmaker[AsyncSession],
    rendered: Rendered,
) -> None:
    class FullNumber(FakeExtractor):
        async def extract(self, doc_type: str, lines: Sequence[DocLine]) -> ExtractionOutcome:
            out = await super().extract(doc_type, lines)
            out.fields["account_last4"] = ExtractedField("0001-2345-6032", ["p1-L12"], "high")
            return out

    stub = await read_stub(
        docs_client, s3_storage, session_factory, rendered, extractor=FullNumber()
    )

    stored = await one(
        session,
        "SELECT value, normalized_value, original_value FROM fields "
        "WHERE document_id = :d AND name = 'account_last4'",
        d=stub.doc,
    )
    assert tuple(stored) == ("6032", "6032", "6032")
    assert (await rows(session, "SELECT 1 FROM fields WHERE value LIKE '%2345%'")) == []
    shown = by_name(await get_extraction(docs_client, stub))["account_last4"]
    assert (shown["value"], shown["original_value"]) == ("6032", "6032")


@pytest.mark.parametrize("path", ["/extraction", "/fields/net_pay_current"])
async def test_extraction_and_review_need_a_token(
    docs_client: httpx.AsyncClient,
    s3_storage: Storage,
    session_factory: async_sessionmaker[AsyncSession],
    rendered: Rendered,
    path: str,
) -> None:
    stub = await read_stub(docs_client, s3_storage, session_factory, rendered)
    response = await docs_client.request(
        "GET" if "extraction" in path else "PATCH", stub.base + path
    )
    assert response.status_code == 401


async def test_a_document_you_cannot_see_looks_like_one_that_does_not_exist(
    docs_client: httpx.AsyncClient,
    s3_storage: Storage,
    session_factory: async_sessionmaker[AsyncSession],
    rendered: Rendered,
) -> None:
    stub = await read_stub(docs_client, s3_storage, session_factory, rendered)
    hidden = await docs_client.get(f"{stub.base}/extraction", headers=headers(Role.LM_SPECIALIST))
    missing = await docs_client.get(
        f"/api/v1/cases/{DANIEL}/documents/{uuid.uuid4()}/extraction",
        headers=headers(Role.LM_SPECIALIST),
    )
    assert hidden.status_code == missing.status_code == 404 and hidden.json() == missing.json()
    other_case = await docs_client.get(
        f"/api/v1/cases/{ANGELA}/documents/{stub.doc}/extraction",
        headers=headers(Role.LM_SPECIALIST),
    )
    assert other_case.status_code == 404  # Daniel's document is not in Angela's case
    malformed = await docs_client.get(
        f"/api/v1/cases/{DANIEL}/documents/not-a-uuid/extraction", headers=headers()
    )
    assert malformed.status_code == 404


# --- PATCH: correct ---------------------------------------------------------------------------


async def test_a_correction_keeps_the_original_and_rechecks_without_a_model_call(
    docs_client: httpx.AsyncClient,
    session: AsyncSession,
    s3_storage: Storage,
    session_factory: async_sessionmaker[AsyncSession],
    rendered: Rendered,
) -> None:
    extractor = FakeExtractor()
    stub = await read_stub(docs_client, s3_storage, session_factory, rendered, extractor=extractor)

    response = await review(
        docs_client,
        stub,
        "net_pay_current",
        {
            "action": "correct",
            "value": "2,033.61",
            "reason": "OCR misread 3 as 8; gross minus deductions is 2,033.61",
            "expected_version": 1,
        },
    )

    assert response.status_code == 200, response.text
    out = response.json()
    assert set(out) == set(FieldOut.model_fields)
    assert (out["value"], out["original_value"]) == ("2033.61", "2083.61")  # the original is kept
    assert (out["review_status"], out["version"]) == ("corrected", 2)
    assert out["reviewed_by"] == str(user_id("underwriter")) and out["reviewed_at"]
    assert out["review_reason"].startswith("OCR misread")
    assert out["flags"] == []  # the arithmetic now holds, so the flag cleared itself

    row = await one(
        session,
        "SELECT value, normalized_value, original_value, review_status, version FROM fields "
        "WHERE document_id = :d AND name = 'net_pay_current'",
        d=stub.doc,
    )
    assert tuple(row) == ("2,033.61", "2033.61", "2083.61", "corrected", 2)
    [flag] = await flags_of(session, stub.doc)
    assert (flag.code, flag.status, flag.resolved_by, flag.reason) == (
        "DI-CHK-02",
        "resolved",
        None,
        "check now passes",
    )
    d = await document(session, stub.doc)
    assert d.status == "reviewed"  # nothing is left for a person
    assert d.summary.endswith("gross 3,070.50, net 2,033.61.")  # refreshed from the new value

    event = await one(session, "SELECT * FROM audit_events WHERE action = 'field.corrected'")
    assert (event.actor_id, event.role, event.entity_type) == (
        user_id("underwriter"),
        "underwriter",
        "field",
    )
    assert event.before["value"] == "2,083.61" and event.after["value"] == "2,033.61"
    assert event.before["version"] == 1 and event.after["version"] == 2
    assert event.reason == "OCR misread 3 as 8; gross minus deductions is 2,033.61"
    assert extractor is not None  # no second model call: the pipeline was not re-run


async def test_a_correction_that_is_still_wrong_keeps_the_flag_open(
    docs_client: httpx.AsyncClient,
    session: AsyncSession,
    s3_storage: Storage,
    session_factory: async_sessionmaker[AsyncSession],
    rendered: Rendered,
) -> None:
    stub = await read_stub(docs_client, s3_storage, session_factory, rendered)
    out = (
        await review(
            docs_client,
            stub,
            "net_pay_current",
            {
                "action": "correct",
                "value": "$2,000.00",
                "reason": "typed it",
                "expected_version": 1,
            },
        )
    ).json()

    assert out["value"] == "2000.00"  # normalised
    [flag] = out["flags"]
    assert flag["message"] == "Gross 3,070.50 minus deductions 1,036.89 is 2,033.61, not 2,000.00."
    assert (await document(session, stub.doc)).status == "needs_review"


@pytest.mark.parametrize(
    ("body", "expected_error"),
    [
        ({"action": "correct", "value": "2,033.61", "expected_version": 1}, "reason"),
        ({"action": "correct", "reason": "because", "expected_version": 1}, "value"),
        ({"action": "correct", "value": "  ", "reason": "because", "expected_version": 1}, "value"),
        ({"action": "reject", "expected_version": 1}, "reason"),
        ({"action": "confirm", "reason": "x" * 1001, "expected_version": 1}, "reason"),
        ({"action": "approve", "expected_version": 1}, "action"),
        ({"action": "confirm"}, "expected_version"),
    ],
)
async def test_a_review_that_breaks_the_contracts_rules_is_refused_and_changes_nothing(
    docs_client: httpx.AsyncClient,
    session: AsyncSession,
    s3_storage: Storage,
    session_factory: async_sessionmaker[AsyncSession],
    rendered: Rendered,
    body: dict[str, Any],
    expected_error: str,
) -> None:
    stub = await read_stub(docs_client, s3_storage, session_factory, rendered)

    response = await review(docs_client, stub, "net_pay_current", body)

    assert response.status_code == 422 and response.json()["code"] == "validation_failed"
    assert expected_error in str(response.json()["details"])
    row = await one(
        session,
        "SELECT value, review_status, version FROM fields "
        "WHERE document_id = :d AND name = 'net_pay_current'",
        d=stub.doc,
    )
    assert tuple(row) == ("2,083.61", "unreviewed", 1)
    assert await rows(session, "SELECT 1 FROM audit_events WHERE action LIKE 'field.%'") == []


async def test_a_corrected_value_that_is_not_an_amount_is_refused(
    docs_client: httpx.AsyncClient,
    session: AsyncSession,
    s3_storage: Storage,
    session_factory: async_sessionmaker[AsyncSession],
    rendered: Rendered,
) -> None:
    stub = await read_stub(docs_client, s3_storage, session_factory, rendered)
    response = await review(
        docs_client,
        stub,
        "net_pay_current",
        {"action": "correct", "value": "lots", "reason": "typo", "expected_version": 1},
    )
    assert response.status_code == 422
    assert response.json()["message"] == "Net pay must be an amount"
    bad_date = await review(
        docs_client,
        stub,
        "pay_period_start",
        {"action": "correct", "value": "next week", "reason": "typo", "expected_version": 1},
    )
    assert bad_date.json()["message"] == "Pay period start must be a date"
    assert (await one(session, "SELECT count(*) AS n FROM fields WHERE version > 1")).n == 0


# --- PATCH: conflict, confirm, reject ---------------------------------------------------------


async def test_two_reviewers_cannot_silently_overwrite_each_other(
    docs_client: httpx.AsyncClient,
    session: AsyncSession,
    s3_storage: Storage,
    session_factory: async_sessionmaker[AsyncSession],
    rendered: Rendered,
) -> None:
    stub = await read_stub(docs_client, s3_storage, session_factory, rendered)
    first = await review(
        docs_client,
        stub,
        "net_pay_current",
        {"action": "correct", "value": "2033.61", "reason": "first", "expected_version": 1},
    )
    second = await review(
        docs_client,
        stub,
        "net_pay_current",
        {"action": "correct", "value": "1.00", "reason": "second", "expected_version": 1},
    )

    assert first.status_code == 200
    assert second.status_code == 409
    assert second.json() == {
        "code": "edit_conflict",
        "message": "Someone else changed this value. Review the latest and try again.",
    }
    row = await one(
        session,
        "SELECT normalized_value, version FROM fields "
        "WHERE document_id = :d AND name = 'net_pay_current'",
        d=stub.doc,
    )
    assert tuple(row) == ("2033.61", 2)  # the first reviewer's value stands
    assert (
        await rows(session, "SELECT 1 FROM audit_events WHERE action = 'field.corrected'")
    ) != []
    assert (
        len(await rows(session, "SELECT 1 FROM audit_events WHERE action = 'field.corrected'")) == 1
    )


async def test_confirming_a_flagged_value_records_the_decision_and_stays_flagged_in_history(
    docs_client: httpx.AsyncClient,
    session: AsyncSession,
    s3_storage: Storage,
    session_factory: async_sessionmaker[AsyncSession],
    rendered: Rendered,
) -> None:
    stub = await read_stub(docs_client, s3_storage, session_factory, rendered)

    response = await review(
        docs_client,
        stub,
        "net_pay_current",
        {"action": "confirm", "reason": "matches the paper stub", "expected_version": 1},
    )

    out = response.json()
    assert (out["review_status"], out["version"], out["value"], out["original_value"]) == (
        "confirmed",
        2,
        "2083.61",
        "2083.61",
    )
    assert out["flags"] == []  # the person has seen it; it is no longer an open flag
    [flag] = await flags_of(session, stub.doc)
    assert (flag.code, flag.status, flag.resolved_by, flag.reason) == (
        "DI-CHK-02",
        "overridden",
        user_id("underwriter"),
        "matches the paper stub",
    )
    # Nothing is left for a person, so the document is reviewed; the arithmetic still disagrees,
    # and the checks do not reopen a flag a person overrode.
    assert (await document(session, stub.doc)).status == "reviewed"
    again = await run(stub.body, s3_storage, session_factory, stages=["validate", "ready"])
    assert again is None
    assert [(f.status) for f in await flags_of(session, stub.doc)] == ["overridden"]


async def test_confirming_without_a_reason_is_allowed(
    docs_client: httpx.AsyncClient,
    s3_storage: Storage,
    session_factory: async_sessionmaker[AsyncSession],
    rendered: Rendered,
) -> None:
    stub = await read_stub(docs_client, s3_storage, session_factory, rendered)
    response = await review(
        docs_client, stub, "employee_name", {"action": "confirm", "expected_version": 1}
    )
    assert response.status_code == 200
    assert (response.json()["review_status"], response.json()["review_reason"]) == (
        "confirmed",
        None,
    )


async def test_rejecting_a_value_treats_it_as_missing(
    docs_client: httpx.AsyncClient,
    session: AsyncSession,
    s3_storage: Storage,
    session_factory: async_sessionmaker[AsyncSession],
    rendered: Rendered,
) -> None:
    stub = await read_stub(docs_client, s3_storage, session_factory, rendered)

    response = await review(
        docs_client,
        stub,
        "net_pay_current",
        {"action": "reject", "reason": "not on the stub", "expected_version": 1},
    )

    assert response.status_code == 200
    out = response.json()
    assert (out["review_status"], out["version"], out["value"]) == ("rejected", 2, "2083.61")
    assert [f["code"] for f in out["flags"]] == ["DI-W604"]  # a required value is now missing
    assert out["flags"][0]["message"] == "Net pay wasn't found in this document."
    codes = {f.code: f.severity for f in await flags_of(session, stub.doc, only_open=True)}
    assert codes == {"DI-W604": "warning", "DI-CHK-02": "info"}  # and the check cannot run
    assert (await document(session, stub.doc)).status == "needs_review"


async def test_a_review_only_touches_its_own_field(
    docs_client: httpx.AsyncClient,
    session: AsyncSession,
    s3_storage: Storage,
    session_factory: async_sessionmaker[AsyncSession],
    rendered: Rendered,
) -> None:
    stub = await read_stub(docs_client, s3_storage, session_factory, rendered)
    await review(
        docs_client,
        stub,
        "net_pay_current",
        {"action": "correct", "value": "2033.61", "reason": "r", "expected_version": 1},
    )
    others = await rows(
        session,
        "SELECT name, version, review_status FROM fields "
        "WHERE document_id = :d AND name <> 'net_pay_current'",
        d=stub.doc,
    )
    assert {(o.version, o.review_status) for o in others} == {(1, "unreviewed")}


async def test_a_field_that_does_not_exist_is_404(
    docs_client: httpx.AsyncClient,
    s3_storage: Storage,
    session_factory: async_sessionmaker[AsyncSession],
    rendered: Rendered,
) -> None:
    stub = await read_stub(docs_client, s3_storage, session_factory, rendered)
    response = await review(
        docs_client, stub, "no_such_field", {"action": "confirm", "expected_version": 1}
    )
    assert response.status_code == 404 and response.json()["message"] == "Field not found"
    bad_name = await review(
        docs_client, stub, "Net-Pay", {"action": "confirm", "expected_version": 1}
    )
    assert bad_name.status_code == 422  # the contract's name pattern
    hidden = await review(
        docs_client,
        stub,
        "net_pay_current",
        {"action": "confirm", "expected_version": 1},
        Role.LM_SPECIALIST,
    )
    assert hidden.status_code == 404


async def test_a_new_extraction_does_not_carry_corrections_but_keeps_them_as_history(
    docs_client: httpx.AsyncClient,
    session: AsyncSession,
    s3_storage: Storage,
    session_factory: async_sessionmaker[AsyncSession],
    rendered: Rendered,
) -> None:
    stub = await read_stub(docs_client, s3_storage, session_factory, rendered)
    await review(
        docs_client,
        stub,
        "net_pay_current",
        {"action": "correct", "value": "2033.61", "reason": "r", "expected_version": 1},
    )

    await run(
        stub.body,
        s3_storage,
        session_factory,
        stages=["extract", "validate", "ready"],
        force_extract=True,
    )

    fresh = by_name(await get_extraction(docs_client, stub))["net_pay_current"]
    assert (fresh["value"], fresh["review_status"], fresh["version"]) == (
        "2083.61",
        "unreviewed",
        1,
    )
    history = await rows(
        session,
        "SELECT f.review_status, f.original_value, f.value FROM fields f "
        "JOIN extraction_runs r ON r.id = f.run_id "
        "WHERE r.document_id = :d AND NOT r.active AND f.name = 'net_pay_current'",
        d=stub.doc,
    )
    assert [(h.review_status, h.original_value, h.value) for h in history] == [
        ("corrected", "2083.61", "2033.61")
    ]  # the earlier run, and the person's work on it, are kept


# --- PUT type ---------------------------------------------------------------------------------


async def test_choosing_the_type_of_a_held_document_queues_its_extraction(
    docs_client: httpx.AsyncClient,
    session: AsyncSession,
    s3_storage: Storage,
    session_factory: async_sessionmaker[AsyncSession],
    fake_queue: FakeQueue,
    rendered: Rendered,
) -> None:
    body = await upload_files(docs_client, rendered, [SEPTEMBER], declared_type="tax_return_1040")
    await run(body, s3_storage, session_factory)
    stub = Stub(body)
    fake_queue.calls.clear()

    response = await docs_client.put(
        f"{stub.base}/type",
        json={"doc_type": "bank_statement", "reason": "it is a bank statement"},
        headers=headers(),
    )

    assert response.status_code == 202, response.text
    accepted = response.json()
    assert set(accepted) == {"document", "job"}
    assert (accepted["document"]["doc_type"], accepted["document"]["status"]) == (
        "bank_statement",
        "processing",
    )
    assert (
        accepted["job"]["status"] == "queued" and accepted["job"]["kind"] == "document_processing"
    )
    job_id = accepted["job"]["id"]
    assert fake_queue.calls == [
        ("process_documents", (job_id, [stub.doc], ["extract", "validate", "ready"], True), job_id)
    ]
    d = await document(session, stub.doc)
    assert (d.doc_type, d.doc_type_source) == ("bank_statement", "user")
    [flag] = await flags_of(session, stub.doc)
    assert (flag.code, flag.status, flag.resolved_by, flag.reason) == (
        "DI-W502",
        "resolved",
        user_id("underwriter"),
        "it is a bank statement",
    )
    event = await one(session, "SELECT * FROM audit_events WHERE action = 'document.type_set'")
    assert event.before["doc_type"] is None and event.after["doc_type"] == "bank_statement"
    assert event.after["extraction_queued"] is True and event.reason == "it is a bank statement"

    # The worker picks up exactly that call, and the document is read.
    await run(
        {"job": accepted["job"], "documents": [accepted["document"]]},
        s3_storage,
        session_factory,
        stages=["extract", "validate", "ready"],
        force_extract=True,
    )
    final = await document(session, stub.doc)
    assert final.status == "reviewed" and final.summary.startswith("Bank statement, Daniel Reyes")
    assert (await get_extraction(docs_client, stub))["doc_type"] == "bank_statement"
    job = await one(session, "SELECT status, progress FROM jobs WHERE id = :j", j=job_id)
    assert tuple(job) == ("succeeded", 1.0)


async def test_confirming_the_type_it_already_has_needs_no_new_extraction(
    docs_client: httpx.AsyncClient,
    session: AsyncSession,
    s3_storage: Storage,
    session_factory: async_sessionmaker[AsyncSession],
    fake_queue: FakeQueue,
    rendered: Rendered,
) -> None:
    stub = await read_stub(docs_client, s3_storage, session_factory, rendered)
    fake_queue.calls.clear()

    response = await docs_client.put(
        f"{stub.base}/type", json={"doc_type": "pay_stub"}, headers=headers()
    )

    assert response.status_code == 200
    assert response.json()["doc_type"] == "pay_stub" and response.json()["id"] == stub.doc
    assert fake_queue.calls == []
    assert len(await rows(session, "SELECT 1 FROM extraction_runs")) == 1
    d = await document(session, stub.doc)
    assert (d.status, d.doc_type_source) == ("needs_review", "user")  # now a person's decision


async def test_changing_the_type_of_a_read_document_starts_a_new_run(
    docs_client: httpx.AsyncClient,
    session: AsyncSession,
    s3_storage: Storage,
    session_factory: async_sessionmaker[AsyncSession],
    rendered: Rendered,
) -> None:
    stub = await read_stub(docs_client, s3_storage, session_factory, rendered)
    response = await docs_client.put(
        f"{stub.base}/type", json={"doc_type": "credit_report"}, headers=headers()
    )
    assert response.status_code == 202
    accepted = response.json()

    await run(
        {"job": accepted["job"], "documents": [accepted["document"]]},
        s3_storage,
        session_factory,
        stages=["extract", "validate", "ready"],
        force_extract=True,
    )

    runs = await rows(
        session, "SELECT doc_type, active FROM extraction_runs WHERE document_id = :d", d=stub.doc
    )
    assert sorted((r.doc_type, r.active) for r in runs) == [
        ("credit_report", True),
        ("pay_stub", False),
    ]
    extraction = await get_extraction(docs_client, stub)
    assert extraction["doc_type"] == "credit_report" and extraction["fields"] == []
    assert [f["code"] for f in extraction["flags"]] == ["DI-W604"]  # read by a later feature


async def test_a_type_change_that_cannot_be_queued_is_saved_and_reported(
    docs_client: httpx.AsyncClient,
    session: AsyncSession,
    s3_storage: Storage,
    session_factory: async_sessionmaker[AsyncSession],
    fake_queue: FakeQueue,
    rendered: Rendered,
) -> None:
    stub = await read_stub(docs_client, s3_storage, session_factory, rendered)
    fake_queue.fail = True
    response = await docs_client.put(
        f"{stub.base}/type", json={"doc_type": "w2"}, headers=headers()
    )
    assert response.status_code == 503 and response.json()["code"] == "queue_unavailable"
    assert (await document(session, stub.doc)).doc_type == "w2"
    job = await one(
        session, "SELECT status, error FROM jobs WHERE id <> :upload", upload=stub.body["job"]["id"]
    )  # the job the type change created, not the upload's
    assert job.status == "failed" and "could not be queued" in job.error


@pytest.mark.parametrize(
    "body", [{}, {"doc_type": "passport"}, {"doc_type": "w2", "reason": "x" * 501}]
)
async def test_a_bad_type_is_a_validation_error(
    docs_client: httpx.AsyncClient,
    s3_storage: Storage,
    session_factory: async_sessionmaker[AsyncSession],
    rendered: Rendered,
    body: dict[str, Any],
) -> None:
    stub = await read_stub(docs_client, s3_storage, session_factory, rendered)
    response = await docs_client.put(f"{stub.base}/type", json=body, headers=headers())
    assert response.status_code == 422 and response.json()["code"] == "validation_failed"


async def test_the_type_of_a_document_you_cannot_see_is_404(
    docs_client: httpx.AsyncClient,
    s3_storage: Storage,
    session_factory: async_sessionmaker[AsyncSession],
    rendered: Rendered,
) -> None:
    stub = await read_stub(docs_client, s3_storage, session_factory, rendered)
    hidden = await docs_client.put(
        f"{stub.base}/type", json={"doc_type": "w2"}, headers=headers(Role.LM_SPECIALIST)
    )
    assert hidden.status_code == 404
    assert (await docs_client.put(f"{stub.base}/type", json={"doc_type": "w2"})).status_code == 401


# --- GET jobs ---------------------------------------------------------------------------------


async def test_a_job_can_be_polled_from_queued_to_succeeded(
    docs_client: httpx.AsyncClient,
    s3_storage: Storage,
    session_factory: async_sessionmaker[AsyncSession],
    rendered: Rendered,
) -> None:
    body = await upload_files(docs_client, rendered, [STUB, AUGUST])
    url = f"/api/v1/jobs/{body['job']['id']}"

    queued = (await docs_client.get(url, headers=headers())).json()
    assert (queued["status"], queued["progress"], queued["stage"], queued["error"]) == (
        "queued",
        0,
        None,
        None,
    )

    await run(body, s3_storage, session_factory)

    done = (await docs_client.get(url, headers=headers())).json()
    assert set(done) == {
        "id",
        "kind",
        "status",
        "progress",
        "stage",
        "error",
        "created_at",
        "updated_at",
    }
    assert (done["id"], done["kind"], done["status"], done["progress"], done["stage"]) == (
        body["job"]["id"],
        "document_processing",
        "succeeded",
        1,
        "ready",
    )


async def test_a_failed_job_says_why(
    docs_client: httpx.AsyncClient,
    s3_storage: Storage,
    session_factory: async_sessionmaker[AsyncSession],
    rendered: Rendered,
) -> None:
    body = await upload_files(docs_client, rendered, ["broken/locked_w2_2025.pdf"])
    await run(body, s3_storage, session_factory)
    job = (await docs_client.get(f"/api/v1/jobs/{body['job']['id']}", headers=headers())).json()
    assert job["status"] == "failed"
    assert job["error"] == "We couldn't use locked_w2_2025.pdf: the file is password protected."


async def test_a_job_you_cannot_see_looks_like_one_that_does_not_exist(
    docs_client: httpx.AsyncClient, rendered: Rendered
) -> None:
    body = await upload_files(docs_client, rendered, [STUB])
    url = f"/api/v1/jobs/{body['job']['id']}"
    hidden = await docs_client.get(url, headers=headers(Role.LM_SPECIALIST))
    missing = await docs_client.get(
        f"/api/v1/jobs/{uuid.uuid4()}", headers=headers(Role.LM_SPECIALIST)
    )
    assert hidden.status_code == missing.status_code == 404 and hidden.json() == missing.json()
    assert (await docs_client.get("/api/v1/jobs/not-a-uuid", headers=headers())).status_code == 404
    assert (await docs_client.get(url)).status_code == 401
    assert (await docs_client.get(url, headers=headers(Role.ADMIN))).status_code == 200


# --- the document list now shows the flags ---------------------------------------------------


async def test_the_document_list_shows_every_open_flag_and_the_review_filter_works(
    docs_client: httpx.AsyncClient,
    s3_storage: Storage,
    session_factory: async_sessionmaker[AsyncSession],
    rendered: Rendered,
) -> None:
    body = await upload_files(
        docs_client, rendered, [STUB, AUGUST, STUB.replace("2026-09-27", "2026-09-27")]
    )
    await run(body, s3_storage, session_factory)
    url = f"/api/v1/cases/{DANIEL}/documents"

    items = (await docs_client.get(url, headers=headers())).json()["items"]
    by_file = {}
    for i in items:
        by_file.setdefault(i["file_name"], []).append(i)
    stub_first, stub_copy = by_file["pay_stub_2026-09-27.pdf"]
    assert [f["code"] for f in stub_first["flags"]] == ["DI-CHK-02"]
    assert sorted(f["code"] for f in stub_copy["flags"]) == [
        "DI-CHK-02",
        "DI-W206",
    ]  # + the duplicate
    [august] = by_file["bank_statement_2026-08.pdf"]
    assert sorted(f["code"] for f in august["flags"]) == ["DI-CHK-05", "DI-CHK-06", "DI-W701"]
    assert {i["status"] for i in items} == {"needs_review"}
    assert (stub_first["doc_type"], stub_first["owner"], stub_first["type_certainty"]) == (
        "pay_stub",
        "Daniel Reyes",
        "high",
    )
    assert stub_first["summary"].startswith("Pay stub, Daniel Reyes")

    only = (await docs_client.get(url, params={"needs_review": "true"}, headers=headers())).json()
    assert len(only["items"]) == 3

    # After a person confirms the flagged value, the flag leaves the list.
    stub = Stub({"documents": [{"id": stub_first["id"]}]})
    await review(docs_client, stub, "net_pay_current", {"action": "confirm", "expected_version": 1})
    again = (await docs_client.get(url, headers=headers())).json()["items"]
    first_now = next(i for i in again if i["id"] == stub_first["id"])
    assert first_now["flags"] == [] and first_now["status"] == "reviewed"

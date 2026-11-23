"""Income analysis through the API, the worker and Postgres: Daniel Reyes (Feature Design 2.8).

The documents are stored as the real reader leaves them (an active extraction run with fields), the
analysis runs in the real worker function against the test database, and the endpoints read it back.
Including overtime must give 6,424.41 at once, keep the system's own decision beside the person's,
and write an audit event; none of it calls a model.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta
from typing import Any

import httpx
import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.enums import Certainty, DocumentStatus, Role
from app.db.models import Document, ExtractionRun
from app.db.models import Field as FieldRow
from app.db.seed import case_id, seed
from app.services import income_runs
from app.services.document_config import get_document_fields
from app.services.normalize import normalize, stored_text
from app.worker import run_income_analysis
from tests.db.conftest import FakeQueue, auth_headers
from tests.services.test_income import RETURN_2025, STUB, W2_2024, W2_2025

DANIEL = case_id("Daniel Reyes — purchase")  # underwriting
ANGELA = case_id("Angela Whitfield — hardship")  # loss mitigation
FIELDS = get_document_fields()
BASE_TIME = datetime(2026, 10, 12, tzinfo=UTC)
BASE = f"/api/v1/cases/{DANIEL}/income-analysis"
CANDIDATE_LABEL = "candidate — qualifying income is determined by the underwriter"


@pytest.fixture(autouse=True)
async def seeded(session: AsyncSession) -> None:
    await seed(session, "demo-pass")


def headers(role: Role = Role.UNDERWRITER) -> dict[str, str]:
    return auth_headers(role)


async def seed_document(
    session: AsyncSession,
    case: uuid.UUID,
    doc_type: str,
    values: dict[str, str],
    *,
    minutes: int = 0,
    status: DocumentStatus = DocumentStatus.NEEDS_REVIEW,
    lines: dict[str, str] | None = None,
    period: tuple[date, date] | None = None,
) -> uuid.UUID:
    """A document with an active extraction run and its fields, as the pipeline leaves it.

    ``lines`` names the line a field was read from (default: ``p1-L`` and the field's number).
    """
    document = Document(
        case_id=case,
        file_name=f"{doc_type}.pdf",
        s3_key=f"k/{uuid.uuid4().hex}",
        sha256=uuid.uuid4().hex * 2,
        mime="application/pdf",
        size_bytes=1,
        status=status,
        doc_type=doc_type,
        created_at=BASE_TIME + timedelta(minutes=minutes),
        period_start=period[0] if period else None,
        period_end=period[1] if period else None,
    )
    session.add(document)
    await session.flush()
    run = ExtractionRun(document_id=document.id, doc_type=doc_type, active=True, provider="fake")
    session.add(run)
    await session.flush()
    for number, (name, value) in enumerate(values.items(), start=1):
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
                line_refs=[(lines or {}).get(name, f"p1-L{number}")],
            )
        )
    await session.flush()
    return document.id


async def seed_daniel(session: AsyncSession, *, with_2024: bool = False) -> dict[str, uuid.UUID]:
    ids = {
        "stub": await seed_document(session, DANIEL, "pay_stub", STUB),
        "w2": await seed_document(session, DANIEL, "w2", W2_2025, minutes=1),
        "return": await seed_document(session, DANIEL, "tax_return_1040", RETURN_2025, minutes=2),
    }
    if with_2024:
        ids["w2_2024"] = await seed_document(session, DANIEL, "w2", W2_2024, minutes=3)
    return ids


async def start(
    client: httpx.AsyncClient, *, case: uuid.UUID = DANIEL, role: Role = Role.UNDERWRITER
) -> httpx.Response:
    return await client.post(f"/api/v1/cases/{case}/income-analysis", headers=headers(role))


async def run_it(
    accepted: dict[str, Any], factory: async_sessionmaker[AsyncSession], **ctx: Any
) -> None:
    await run_income_analysis(
        {"session_factory": factory, **ctx}, accepted["job"]["id"], accepted["analysis_id"]
    )


async def analyse(
    client: httpx.AsyncClient, factory: async_sessionmaker[AsyncSession]
) -> dict[str, Any]:
    response = await start(client)
    assert response.status_code == 202, response.text
    accepted = response.json()
    await run_it(accepted, factory)
    return accepted  # type: ignore[no-any-return]


async def latest(client: httpx.AsyncClient, **kwargs: Any) -> dict[str, Any]:
    response = await client.get(f"{BASE}/latest", headers=headers(**kwargs))
    assert response.status_code == 200, response.text
    return response.json()  # type: ignore[no-any-return]


def part(analysis: dict[str, Any], kind: str) -> dict[str, Any]:
    return next(c for c in analysis["components"] if c["component"] == kind)


async def rows(session: AsyncSession, sql: str, **params: Any) -> list[Any]:
    return list((await session.execute(sa.text(sql), params)).all())


# --- running it -----------------------------------------------------------------------------


async def test_running_the_analysis_queues_a_job_and_the_worker_stores_the_result(
    docs_client: httpx.AsyncClient,
    session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
    fake_queue: FakeQueue,
) -> None:
    await seed_daniel(session)
    response = await start(docs_client)

    assert response.status_code == 202
    accepted = response.json()
    assert accepted["job"]["kind"] == "income_analysis" and accepted["job"]["status"] == "queued"
    assert fake_queue.calls == [
        (
            "run_income_analysis",
            (accepted["job"]["id"], accepted["analysis_id"]),
            accepted["job"]["id"],
        )
    ]
    queued = (await rows(session, "SELECT status, job_id FROM analysis_runs"))[0]
    assert (queued.status, str(queued.job_id)) == ("queued", accepted["job"]["id"])

    await run_it(accepted, session_factory)
    job = (await rows(session, "SELECT status, stage, progress, error, attempts FROM jobs"))[0]
    assert tuple(job) == ("succeeded", "done", 1.0, None, 1)
    run = (await rows(session, "SELECT status, finished_at, config_versions FROM analysis_runs"))[0]
    assert run.status == "succeeded" and run.finished_at is not None
    assert set(run.config_versions) == {"income_method", "thresholds"}
    assert run.config_versions["income_method"]["version"] == "2026-11-19.1"
    assert len(run.config_versions["income_method"]["hash"]) == 64


async def test_the_settings_a_run_used_are_recorded_once(
    docs_client: httpx.AsyncClient,
    session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await seed_daniel(session)
    await analyse(docs_client, session_factory)
    await analyse(docs_client, session_factory)  # the same files again
    versions = await rows(
        session, "SELECT kind, name, version, label, active FROM config_versions ORDER BY kind"
    )
    assert [tuple(v) for v in versions] == [
        ("income_method", "income_method", "2026-11-19.1", "illustrative", True),
        ("thresholds", "thresholds", "2026-11-24.1", "illustrative", True),
    ]


async def test_the_job_and_the_run_are_audited(
    docs_client: httpx.AsyncClient,
    session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await seed_daniel(session)
    await analyse(docs_client, session_factory)
    events = await rows(
        session,
        "SELECT action, role, after FROM audit_events WHERE action LIKE 'income.%' ORDER BY id",
    )
    assert [(e.action, e.role) for e in events] == [
        ("income.run_requested", "underwriter"),
        ("income.analysed", "worker"),
    ]
    assert events[1].after["candidate_monthly_income"] == "5980.00"
    assert events[1].after["components"] == 3


# --- reading it -----------------------------------------------------------------------------


async def test_the_latest_analysis_has_daniels_figures(
    docs_client: httpx.AsyncClient,
    session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await seed_daniel(session)
    await analyse(docs_client, session_factory)
    analysis = await latest(docs_client)

    assert analysis["status"] == "succeeded" and analysis["case_id"] == str(DANIEL)
    assert analysis["candidate_monthly_income"] == "5980.00"
    assert analysis["candidate_label"] == CANDIDATE_LABEL
    assert [c["component"] for c in analysis["components"]] == ["base", "overtime", "bonus"]
    base, overtime, bonus = (part(analysis, k) for k in ("base", "overtime", "bonus"))
    assert (base["current_period"], base["ytd"], base["monthly"]) == (
        "2760.00",
        "52440.00",
        "5980.00",
    )
    assert (overtime["monthly"], bonus["monthly"]) == ("444.41", "228.34")
    assert (base["included"], overtime["included"], bonus["included"]) == (True, False, False)
    assert overtime["exclusion_reason"] == (
        "Overtime is excluded: its documented history is 9 months (2026 only), "
        "and 24 months are needed."
    )
    assert base["borrower"] == "Daniel Reyes" and base["employer"].startswith("Cedar Valley")
    assert overtime["override"] is None  # a person has not touched it


async def test_every_figure_shows_its_working_and_where_it_was_read(
    docs_client: httpx.AsyncClient,
    session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    ids = await seed_daniel(session)
    await analyse(docs_client, session_factory)
    analysis = await latest(docs_client)

    calc = part(analysis, "base")["calculation"]
    assert calc["working"] == "34.50 x 80.00 x 26 / 12 = 5,980.00"
    assert calc["formula"] == "rate x regular hours x periods per year / 12"
    assert calc["config_version"] == "income_method@2026-11-19.1, thresholds@2026-11-24.1"
    assert calc["inputs"] == {"rate": "34.50", "hours": "80.00", "periods_per_year": "26"}
    assert {e["document_id"] for e in calc["evidence"]} == {str(ids["stub"])}
    assert {"earnings_001_hours", "earnings_001_rate"} <= {e["field"] for e in calc["evidence"]}
    assert all(e["line_ids"] for e in calc["evidence"])
    assert analysis["candidate"]["working"] == "5,980.00 = 5,980.00 (Base pay)"
    names = {c["name"] for c in analysis["calculations"]}
    assert {"periods_elapsed", "gross_pay_pace_2026", "box5_minus_box1", "w2_box5_2025"} <= names
    assert "base_monthly" not in names  # a component's own calculation is on the component


async def test_the_flags_come_with_their_working_and_the_documents_they_compare(
    docs_client: httpx.AsyncClient,
    session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    ids = await seed_daniel(session)
    await analyse(docs_client, session_factory)
    analysis = await latest(docs_client)

    assert sorted((f["code"], f["severity"]) for f in analysis["flags"]) == [
        ("INC-CHK-03", "info"),
        ("INC-CHK-04", "info"),
        ("INC-W101", "warning"),
        ("INC-W101", "warning"),
    ]
    deferral = next(f for f in analysis["flags"] if f["code"] == "INC-CHK-03")
    assert deferral["working"] == (
        "74,298.60 - 69,840.68 = 4,457.92; deferrals 4,457.92 (tolerance 22.29)"
    )
    assert {r["document_id"] for r in deferral["refs"]} == {str(ids["w2"])}
    stored = (
        await rows(
            session,
            "SELECT feature, entity_type, status FROM flags WHERE feature = 'income'",
        )
    )[0]
    assert tuple(stored) == ("income", "income_check", "open")


async def test_there_are_no_explanations_until_the_explanation_call_exists(
    docs_client: httpx.AsyncClient,
    session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await seed_daniel(session)
    await analyse(docs_client, session_factory)
    analysis = await latest(docs_client)
    assert analysis["explanations"] == [] and analysis["explanations_note"] == (
        "explanations not generated"
    )


async def test_with_the_2024_w2_the_trend_is_5_49_percent_and_2024_is_explained_too(
    docs_client: httpx.AsyncClient,
    session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await seed_daniel(session, with_2024=True)
    await analyse(docs_client, session_factory)
    messages = [f["message"] for f in (await latest(docs_client))["flags"]]
    assert "Medicare wages rose 5.49% from 2024 (70,431.80) to 2025 (74,298.60)." in messages


async def test_a_case_with_no_documents_gets_an_empty_analysis_that_says_what_is_missing(
    docs_client: httpx.AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    await analyse(docs_client, session_factory)
    analysis = await latest(docs_client)
    assert analysis["components"] == [] and analysis["candidate_monthly_income"] == "0.00"
    assert analysis["candidate"]["working"] == "No component is included = 0.00"
    assert {f["code"] for f in analysis["flags"]} >= {"INC-W103", "INC-CHK-01", "INC-CHK-02"}
    assert {f["severity"] for f in analysis["flags"]} == {"info"}


async def test_only_this_cases_documents_are_read(
    docs_client: httpx.AsyncClient,
    session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await seed_document(session, ANGELA, "pay_stub", STUB)  # another case's stub
    await analyse(docs_client, session_factory)
    assert (await latest(docs_client))["components"] == []


# --- including and excluding ----------------------------------------------------------------


async def test_including_overtime_gives_6424_41_at_once_and_keeps_the_original(
    docs_client: httpx.AsyncClient,
    session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await seed_daniel(session)
    await analyse(docs_client, session_factory)
    overtime = part(await latest(docs_client), "overtime")

    response = await docs_client.patch(
        f"{BASE}/latest/components/{overtime['id']}",
        json={"included": True, "reason": "Two years of overtime on the VOE"},
        headers=headers(),
    )

    assert response.status_code == 200, response.text
    analysis = response.json()
    assert analysis["candidate_monthly_income"] == "6424.41"
    assert analysis["candidate"]["working"] == "5,980.00 + 444.41 = 6,424.41 (Base pay, Overtime)"
    changed = part(analysis, "overtime")
    assert changed["included"] is True and changed["exclusion_reason"] is None
    # What the system decided is still there, beside the person's change.
    assert changed["system_included"] is False
    assert changed["system_exclusion_reason"].startswith("Overtime is excluded: its documented")
    assert changed["override"]["included"] is True
    assert changed["override"]["reason"] == "Two years of overtime on the VOE"
    assert changed["override"]["by"] and changed["override"]["at"]
    assert (await latest(docs_client))["candidate_monthly_income"] == "6424.41"  # it was saved


async def test_excluding_it_again_goes_back_and_a_reason_is_kept_for_each_change(
    docs_client: httpx.AsyncClient,
    session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await seed_daniel(session)
    await analyse(docs_client, session_factory)
    overtime = part(await latest(docs_client), "overtime")
    url = f"{BASE}/latest/components/{overtime['id']}"
    await docs_client.patch(url, json={"included": True, "reason": "Verified"}, headers=headers())
    response = await docs_client.patch(
        url,
        json={"included": False, "reason": "Employer says it ends in January"},
        headers=headers(),
    )

    analysis = response.json()
    assert analysis["candidate_monthly_income"] == "5980.00"
    back = part(analysis, "overtime")
    assert back["included"] is False
    assert back["exclusion_reason"] == "Employer says it ends in January"
    assert back["system_exclusion_reason"].startswith("Overtime is excluded: its documented")
    events = await rows(
        session,
        "SELECT action, before, after, reason FROM audit_events "
        "WHERE entity_type = 'income_component' ORDER BY id",
    )
    assert [(e.action, e.reason) for e in events] == [
        ("income.component_included", "Verified"),
        ("income.component_excluded", "Employer says it ends in January"),
    ]
    assert events[0].before["candidate_monthly_income"] == "5980.00"
    assert events[0].after["candidate_monthly_income"] == "6424.41"
    assert events[0].before["included"] is False and events[0].after["included"] is True
    assert events[1].before["candidate_monthly_income"] == "6424.41"
    assert events[1].after["candidate_monthly_income"] == "5980.00"


async def test_a_change_needs_a_reason_and_nothing_else(
    docs_client: httpx.AsyncClient,
    session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await seed_daniel(session)
    await analyse(docs_client, session_factory)
    url = f"{BASE}/latest/components/{part(await latest(docs_client), 'overtime')['id']}"
    for body in (
        {"included": True},
        {"included": True, "reason": ""},
        {"included": True, "reason": "   "},
        {"included": True, "reason": "x" * 501},
        {"reason": "no decision"},
        {"included": True, "reason": "ok", "monthly": "1.00"},  # the figures are not editable
        {"included": "maybe", "reason": "ok"},
    ):
        response = await docs_client.patch(url, json=body, headers=headers())
        assert response.status_code == 422, body
    assert (await latest(docs_client))["candidate_monthly_income"] == "5980.00"
    assert (
        await rows(session, "SELECT 1 FROM audit_events WHERE action LIKE 'income.component%'")
        == []
    )


async def test_a_component_that_is_not_there_is_not_found(
    docs_client: httpx.AsyncClient,
    session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await seed_daniel(session)
    await analyse(docs_client, session_factory)
    body = {"included": True, "reason": "ok"}
    for component in (str(uuid.uuid4()), "not-a-uuid"):
        response = await docs_client.patch(
            f"{BASE}/latest/components/{component}", json=body, headers=headers()
        )
        assert response.status_code == 404 and response.json()["code"] == "not_found"


async def test_an_older_analysis_cannot_be_changed_once_a_newer_one_exists(
    docs_client: httpx.AsyncClient,
    session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await seed_daniel(session)
    await analyse(docs_client, session_factory)
    old = part(await latest(docs_client), "overtime")
    await analyse(docs_client, session_factory)  # a newer run

    response = await docs_client.patch(
        f"{BASE}/latest/components/{old['id']}",
        json={"included": True, "reason": "ok"},
        headers=headers(),
    )
    assert response.status_code == 409 and response.json()["code"] == "stale_analysis"
    assert len(await rows(session, "SELECT 1 FROM analysis_runs")) == 2  # the first one is kept
    assert len(await rows(session, "SELECT 1 FROM income_components")) == 6


# --- runs, history and failures --------------------------------------------------------------


async def test_the_newest_run_is_the_latest_and_the_older_one_is_kept(
    docs_client: httpx.AsyncClient,
    session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await seed_daniel(session)
    first = await analyse(docs_client, session_factory)
    second = await analyse(docs_client, session_factory)
    assert first["analysis_id"] != second["analysis_id"]
    assert (await latest(docs_client))["id"] == second["analysis_id"]
    assert len(await rows(session, "SELECT 1 FROM analysis_runs")) == 2
    assert (
        len(
            await rows(
                session,
                "SELECT 1 FROM calculations WHERE run_id = :r",
                r=uuid.UUID(first["analysis_id"]),
            )
        )
        > 5
    )


async def test_running_a_job_twice_stores_one_result_not_two(
    docs_client: httpx.AsyncClient,
    session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await seed_daniel(session)
    accepted = await analyse(docs_client, session_factory)
    await run_it(accepted, session_factory)  # a repeated delivery of the same job
    assert len(await rows(session, "SELECT 1 FROM income_components")) == 3
    assert len(await rows(session, "SELECT 1 FROM flags WHERE feature = 'income'")) == 4
    names = [r[0] for r in await rows(session, "SELECT name FROM calculations")]
    assert len(names) == len(set(names))


async def test_a_failure_in_the_analysis_fails_the_job_and_leaks_no_document_text(
    docs_client: httpx.AsyncClient,
    session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    await seed_daniel(session)

    def explode(*_: Any, **__: Any) -> Any:
        raise RuntimeError("Gross pay 3,070.50 Daniel Reyes")

    monkeypatch.setattr(income_runs, "analyze", explode)
    response = await start(docs_client)
    await run_it(response.json(), session_factory)

    job = (await rows(session, "SELECT status, error FROM jobs"))[0]
    assert (job.status, job.error) == ("failed", "The income analysis could not be completed.")
    run = (await rows(session, "SELECT status, finished_at FROM analysis_runs"))[0]
    assert run.status == "failed" and run.finished_at is not None
    assert "3,070.50" not in caplog.text and "Daniel" not in caplog.text
    assert "RuntimeError" in caplog.text  # the class name is logged, never the message


async def test_a_queue_that_is_down_is_a_503_and_the_run_is_marked_failed(
    docs_client: httpx.AsyncClient, session: AsyncSession, fake_queue: FakeQueue
) -> None:
    fake_queue.fail = True
    response = await start(docs_client)
    assert response.status_code == 503 and response.json()["code"] == "queue_unavailable"
    job = (await rows(session, "SELECT status, error FROM jobs"))[0]
    assert job.status == "failed" and "could not be queued" in job.error
    assert (await rows(session, "SELECT status FROM analysis_runs"))[0].status == "failed"


# --- who may ask ----------------------------------------------------------------------------


async def test_no_analysis_yet_is_a_404(docs_client: httpx.AsyncClient) -> None:
    response = await docs_client.get(f"{BASE}/latest", headers=headers())
    assert response.status_code == 404 and response.json()["code"] == "not_found"


async def test_a_case_the_caller_cannot_see_is_a_404_on_every_endpoint(
    docs_client: httpx.AsyncClient,
    session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await seed_daniel(session)
    await analyse(docs_client, session_factory)
    component = part(await latest(docs_client), "overtime")["id"]
    lm = headers(Role.LM_SPECIALIST)  # Daniel's case is a Pillar 1 case

    assert (await docs_client.post(BASE, headers=lm)).status_code == 404
    assert (await docs_client.get(f"{BASE}/latest", headers=lm)).status_code == 404
    patch = await docs_client.patch(
        f"{BASE}/latest/components/{component}", json={"included": True, "reason": "x"}, headers=lm
    )
    assert patch.status_code == 404
    assert (await latest(docs_client))["candidate_monthly_income"] == "5980.00"


async def test_the_admin_sees_both_pillars_and_no_token_is_a_401(
    docs_client: httpx.AsyncClient,
    session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await seed_daniel(session)
    await analyse(docs_client, session_factory)
    assert (await docs_client.get(f"{BASE}/latest", headers=headers(Role.ADMIN))).status_code == 200
    assert (await docs_client.get(f"{BASE}/latest")).status_code == 401
    assert (await docs_client.post(BASE)).status_code == 401
    assert (
        await docs_client.patch(f"{BASE}/latest/components/{uuid.uuid4()}", json={})
    ).status_code == 401


async def test_a_malformed_case_id_is_a_404(docs_client: httpx.AsyncClient) -> None:
    response = await docs_client.get("/api/v1/cases/nope/income-analysis/latest", headers=headers())
    assert response.status_code == 404

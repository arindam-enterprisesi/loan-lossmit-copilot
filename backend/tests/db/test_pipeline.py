"""The pipeline end to end: upload, then ingest -> classify -> extract -> validate -> ready.

Each test uploads through the API (real rows, moto S3, a fake queue) and runs the real
``process_documents`` worker function against Postgres, with the rule-based fake reader standing in
for the model. The two cases the Feature Design names are here: Daniel's pay stub must raise the
net pay arithmetic flag, and the August statement must be flagged incomplete.
"""

from __future__ import annotations

import io
import json
import uuid
from collections.abc import Sequence
from typing import Any

import httpx
import pytest
import sqlalchemy as sa
from reportlab.pdfgen import canvas
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession, async_sessionmaker

from app.db.enums import Role
from app.db.seed import case_id, seed
from app.llm.gateway import Gateway, GatewayError
from app.llm.types import AdapterResponse
from app.services.classification import Classification, LlmClassifier
from app.services.doc_lines import DocLine
from app.services.extractor import ExtractedField, ExtractionOutcome
from app.services.fake_reader import FakeClassifier, FakeExtractor
from app.services.ingestion_config import IngestionConfig
from app.storage import Storage
from app.worker import process_documents
from tests.conftest import Rendered
from tests.db.test_documents_api import rows, upload
from tests.llm.fakes import FakeAdapter, fake_config
from tests.services.test_llm_extractor import daniel_pay_stub_reply, extractor_for

DANIEL = case_id("Daniel Reyes — purchase")
ANGELA = case_id("Angela Whitfield — hardship")
STUB = "daniel_reyes/pay_stub_2026-09-27.pdf"
AUGUST = "daniel_reyes/bank_statement_2026-08.pdf"
SEPTEMBER = "daniel_reyes/bank_statement_2026-09.pdf"
CREDIT_REPORT = "daniel_reyes/credit_report_2026-10-12.pdf"  # classified here, read by Feature 4
ANGELA_JULY = "angela_whitfield/bank_statement_2026-07.pdf"
CONFIG = IngestionConfig(version="t", label="illustrative", max_file_mb=25, render_dpi=50)
NET_PAY_MESSAGE = "Gross 3,070.50 minus deductions 1,036.89 is 2,033.61, not 2,083.61."


@pytest.fixture(autouse=True)
async def seeded(session: AsyncSession) -> None:
    await seed(session, "demo-pass")


class Counting:
    """Wraps a reader and counts how often the pipeline calls it."""

    def __init__(self, inner: Any) -> None:
        self.inner, self.calls = inner, 0

    async def classify(self, lines: Sequence[DocLine]) -> Classification:
        self.calls += 1
        return await self.inner.classify(lines)  # type: ignore[no-any-return]

    async def extract(self, doc_type: str, lines: Sequence[DocLine]) -> ExtractionOutcome:
        self.calls += 1
        return await self.inner.extract(doc_type, lines)  # type: ignore[no-any-return]


class Failing:
    def __init__(self, *, task: str = "classify") -> None:
        self.task = task

    async def classify(self, lines: Sequence[DocLine]) -> Classification:
        raise GatewayError("classify", "classify@1", "provider call failed: HTTP 403")

    async def extract(self, doc_type: str, lines: Sequence[DocLine]) -> ExtractionOutcome:
        raise GatewayError("extract", "extract@1", "output failed schema validation")


async def upload_files(
    client: httpx.AsyncClient,
    rendered: Rendered,
    paths: Sequence[str],
    *,
    case: uuid.UUID = DANIEL,
    role: Role = Role.UNDERWRITER,
    declared_type: str | None = None,
) -> dict[str, Any]:
    files = [(p.split("/")[-1], rendered.read(p)) for p in paths]
    response = await upload(client, case, files, role=role, declared_type=declared_type)
    assert response.status_code == 202, response.text
    return response.json()  # type: ignore[no-any-return]


async def run(
    body: dict[str, Any],
    storage: Storage,
    factory: async_sessionmaker[AsyncSession],
    *,
    stages: list[str] | None = None,
    force_extract: bool = False,
    **ctx: Any,
) -> None:
    context = {
        "storage": storage,
        "session_factory": factory,
        "ingestion_config": CONFIG,
        "classifier": FakeClassifier(),
        "extractor": FakeExtractor(),
        **ctx,
    }
    await process_documents(
        context,
        body["job"]["id"],
        [d["id"] for d in body["documents"]],
        stages,
        force_extract,
    )


async def one(session: AsyncSession, sql: str, **params: Any) -> Any:
    [row] = await rows(session, sql, **params)
    return row


async def document(session: AsyncSession, doc_id: str) -> Any:
    return await one(
        session,
        "SELECT status, doc_type, doc_type_source, doc_type_certainty, declared_type, page_count, "
        "borrower, period_start, period_end, summary FROM documents WHERE id = :d",
        d=doc_id,
    )


async def flags_of(session: AsyncSession, doc_id: str, *, only_open: bool = False) -> list[Any]:
    return await rows(
        session,
        "SELECT fl.entity_type, fl.code, fl.severity, fl.message, fl.status, fl.resolved_by, "
        "fl.reason, fl.evidence, f.name AS field FROM flags fl "
        "LEFT JOIN fields f ON fl.entity_type = 'field' AND f.id = fl.entity_id "
        "WHERE (fl.entity_type = 'document' AND fl.entity_id = :d) "
        "   OR (fl.entity_type = 'field' AND f.document_id = :d) "
        + ("AND fl.status = 'open' " if only_open else "")
        + "ORDER BY fl.code, f.name",
        d=doc_id,
    )


def small_pdf(lines: Sequence[str]) -> bytes:
    buffer = io.BytesIO()
    pdf = canvas.Canvas(buffer, invariant=1)
    y = 750
    for text in lines:
        pdf.drawString(54, y, text)
        y -= 18
    pdf.save()
    return buffer.getvalue()


# --- Daniel's pay stub: the net pay arithmetic flag ------------------------------------------


async def test_daniels_stub_raises_the_net_pay_flag(
    docs_client: httpx.AsyncClient,
    session: AsyncSession,
    s3_storage: Storage,
    session_factory: async_sessionmaker[AsyncSession],
    rendered: Rendered,
) -> None:
    body = await upload_files(docs_client, rendered, [STUB])
    [doc] = body["documents"]

    await run(body, s3_storage, session_factory)

    job = await one(session, "SELECT status, stage, progress, error, attempts FROM jobs")
    assert tuple(job) == ("succeeded", "ready", 1.0, None, 1)
    d = await document(session, doc["id"])
    assert (d.status, d.doc_type, d.doc_type_source, d.doc_type_certainty) == (
        "needs_review",
        "pay_stub",
        "ai",
        "high",
    )
    assert (d.borrower, str(d.period_start), str(d.period_end), d.page_count) == (
        "Daniel Reyes",
        "2026-09-14",
        "2026-09-27",
        2,
    )
    assert d.summary == (
        "Pay stub, Daniel Reyes, 2026-09-14 to 2026-09-27: gross 3,070.50, net 2,083.61."
    )

    # One extraction run, tagged as the fake's, with the printed (wrong) net pay and its line.
    run_row = await one(
        session,
        "SELECT doc_type, active, provider, model, prompt_id, signals FROM extraction_runs "
        "WHERE document_id = :d",
        d=doc["id"],
    )
    assert tuple(run_row) == ("pay_stub", True, "fake", "rule-based-v1", "fake-extract@1", [])
    net = await one(
        session,
        "SELECT value, normalized_value, original_value, line_refs, review_status, version, "
        "certainty FROM fields WHERE document_id = :d AND name = 'net_pay_current'",
        d=doc["id"],
    )
    assert tuple(net) == ("2,083.61", "2083.61", "2083.61", ["p1-L31"], "unreviewed", 1, "high")
    account = await one(
        session,
        "SELECT value, normalized_value, original_value FROM fields "
        "WHERE document_id = :d AND name = 'account_last4'",
        d=doc["id"],
    )
    assert tuple(account) == ("6032", "6032", "6032")  # only the last four digits are stored

    [flag] = await flags_of(session, doc["id"])  # the only flag: every other check passes
    assert (flag.entity_type, flag.field, flag.code, flag.severity, flag.status) == (
        "field",
        "net_pay_current",
        "DI-CHK-02",
        "warning",
        "open",
    )
    assert flag.message == NET_PAY_MESSAGE
    assert flag.evidence["page"] == 1
    assert flag.evidence["line_ids"] == ["p1-L17", "p1-L25", "p1-L31"]
    assert set(flag.evidence["bbox"]) == {"x0", "y0", "x1", "y1"}
    assert flag.evidence["working"]["expected"] == "2033.61"
    assert flag.evidence["working"]["printed"] == "2083.61"

    actions = await rows(
        session, "SELECT action FROM audit_events WHERE role = 'worker' ORDER BY id"
    )
    assert [a.action for a in actions] == [
        "document.ingested",
        "document.classified",
        "document.extracted",
        "document.validated",
    ]


async def test_the_august_statement_is_flagged_incomplete(
    docs_client: httpx.AsyncClient,
    session: AsyncSession,
    s3_storage: Storage,
    session_factory: async_sessionmaker[AsyncSession],
    rendered: Rendered,
) -> None:
    body = await upload_files(docs_client, rendered, [AUGUST])
    [doc] = body["documents"]

    await run(body, s3_storage, session_factory)

    assert (await document(session, doc["id"])).status == "needs_review"
    by_code = {f.code: f for f in await flags_of(session, doc["id"])}
    assert set(by_code) == {"DI-W701", "DI-CHK-05", "DI-CHK-06"}
    pages = by_code["DI-W701"]
    assert pages.entity_type == "document"
    assert pages.message == (
        "Incomplete: this document says it has 3 pages, but 2 were uploaded; page 3 is missing."
    )
    assert pages.evidence["line_ids"] == ["p1-L26", "p2-L17"]  # the "Page 1 of 3" footers
    assert by_code["DI-CHK-05"].message == (
        "Opening balance 5,845.26 plus transactions 881.00 is 6,726.26, "
        "not the closing balance 6,455.13."
    )
    printed = await rows(
        session,
        "SELECT page_no, printed_page_label FROM pages WHERE document_id = :d ORDER BY page_no",
        d=doc["id"],
    )
    assert [(p.page_no, p.printed_page_label) for p in printed] == [
        (1, "Page 1 of 3"),
        (2, "Page 2 of 3"),
    ]


async def test_a_statement_declared_as_a_tax_return_waits_for_the_type_to_be_chosen(
    docs_client: httpx.AsyncClient,
    session: AsyncSession,
    s3_storage: Storage,
    session_factory: async_sessionmaker[AsyncSession],
    rendered: Rendered,
) -> None:
    body = await upload_files(docs_client, rendered, [SEPTEMBER], declared_type="tax_return_1040")
    [doc] = body["documents"]

    await run(body, s3_storage, session_factory)

    d = await document(session, doc["id"])
    assert (d.status, d.doc_type, d.declared_type, d.doc_type_certainty) == (
        "type_needed",
        None,
        "tax_return_1040",
        "high",
    )
    [flag] = await flags_of(session, doc["id"])
    assert (flag.entity_type, flag.code, flag.severity, flag.status) == (
        "document",
        "DI-W502",
        "warning",
        "open",
    )
    assert flag.message == (
        "This looks like a bank statement, but you chose tax return (Form 1040). Which is right?"
    )
    assert flag.evidence["predicted"] == "bank_statement"
    assert flag.evidence["selected"] == "tax_return_1040"
    # Extraction is held: no run, no fields. Waiting for a choice is not a failure.
    assert (
        await rows(session, "SELECT 1 FROM extraction_runs WHERE document_id = :d", d=doc["id"])
        == []
    )
    job = await one(session, "SELECT status, progress, error FROM jobs")
    assert tuple(job) == ("succeeded", 1.0, None)


async def test_a_document_with_nothing_for_a_person_to_review_ends_reviewed(
    docs_client: httpx.AsyncClient,
    session: AsyncSession,
    s3_storage: Storage,
    session_factory: async_sessionmaker[AsyncSession],
    rendered: Rendered,
) -> None:
    body = await upload_files(
        docs_client, rendered, [ANGELA_JULY], case=ANGELA, role=Role.LM_SPECIALIST
    )
    [doc] = body["documents"]
    await run(body, s3_storage, session_factory)

    d = await document(session, doc["id"])
    assert d.status == "reviewed" and d.borrower == "Angela Whitfield"
    assert d.summary.startswith("Bank statement, Angela Whitfield, Lakeside Credit Union, ")
    assert await flags_of(session, doc["id"], only_open=True) == []


async def test_a_type_nobody_can_read_yet_says_so(
    docs_client: httpx.AsyncClient,
    session: AsyncSession,
    s3_storage: Storage,
    session_factory: async_sessionmaker[AsyncSession],
    rendered: Rendered,
) -> None:
    body = await upload_files(docs_client, rendered, [CREDIT_REPORT])
    [doc] = body["documents"]
    await run(body, s3_storage, session_factory)

    d = await document(session, doc["id"])
    assert (d.status, d.doc_type, d.summary) == ("needs_review", "credit_report", None)
    [flag] = await flags_of(session, doc["id"])
    assert (flag.code, flag.message) == ("DI-W604", "No fields were extracted from this document.")
    assert await rows(session, "SELECT 1 FROM fields WHERE document_id = :d", d=doc["id"]) == []


async def test_an_unrecognised_document_waits_for_a_person_to_choose(
    docs_client: httpx.AsyncClient,
    session: AsyncSession,
    s3_storage: Storage,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    pdf = small_pdf(["Weekly newsletter", "Lunch menu inside"])
    response = await upload(docs_client, DANIEL, [("news.pdf", pdf)])
    body = response.json()
    [doc] = body["documents"]
    await run(body, s3_storage, session_factory)

    d = await document(session, doc["id"])
    assert (d.status, d.doc_type, d.doc_type_certainty) == ("type_needed", None, "low")
    [flag] = await flags_of(session, doc["id"])
    assert (flag.code, flag.message) == (
        "DI-W501",
        "We couldn't tell what this document is. Choose its type.",
    )


# --- a whole upload: progress, and what a failure does ---------------------------------------


async def test_job_progress_counts_every_stage_of_every_document(
    docs_client: httpx.AsyncClient,
    conn: AsyncConnection,
    session: AsyncSession,
    s3_storage: Storage,
    session_factory: async_sessionmaker[AsyncSession],
    rendered: Rendered,
) -> None:
    seen: list[tuple[float, str]] = []

    class Probe:
        async def classify(self, lines: Sequence[DocLine]) -> Classification:
            row = (await conn.execute(sa.text("SELECT progress, stage FROM jobs"))).one()
            seen.append((row.progress, row.stage))
            return await FakeClassifier().classify(lines)

    body = await upload_files(docs_client, rendered, [STUB, AUGUST])
    await run(body, s3_storage, session_factory, classifier=Probe())

    # Two documents x five stages = ten steps. classify is stage two of each document.
    assert seen == [(0.1, "ingest"), (0.6, "ingest")]
    job = await one(session, "SELECT status, stage, progress FROM jobs")
    assert tuple(job) == ("succeeded", "ready", 1.0)


async def test_a_document_that_cannot_be_read_fails_without_stopping_the_others(
    docs_client: httpx.AsyncClient,
    session: AsyncSession,
    s3_storage: Storage,
    session_factory: async_sessionmaker[AsyncSession],
    rendered: Rendered,
) -> None:
    locked = rendered.read("broken/locked_w2_2025.pdf")
    response = await upload(
        docs_client, DANIEL, [("locked.pdf", locked), (STUB, rendered.read(STUB))]
    )
    body = response.json()
    locked_doc, stub_doc = body["documents"]
    await run(body, s3_storage, session_factory)

    assert (await document(session, locked_doc["id"])).status == "failed"
    assert (await document(session, stub_doc["id"])).status == "needs_review"
    job = await one(session, "SELECT status, progress, error FROM jobs")
    assert job.status == "failed" and job.progress == 1.0
    assert job.error == "We couldn't use locked.pdf: the file is password protected."
    [flag] = await flags_of(session, locked_doc["id"])
    assert (flag.code, flag.severity) == ("DI-E201", "error")
    assert flag.message == "We couldn't use this file: the file is password protected."


async def test_a_model_that_fails_marks_the_document_failed_and_a_rerun_recovers(
    docs_client: httpx.AsyncClient,
    session: AsyncSession,
    s3_storage: Storage,
    session_factory: async_sessionmaker[AsyncSession],
    rendered: Rendered,
) -> None:
    body = await upload_files(docs_client, rendered, [STUB])
    [doc] = body["documents"]

    await run(body, s3_storage, session_factory, extractor=Failing())

    assert (await document(session, doc["id"])).status == "failed"
    [flag] = await flags_of(session, doc["id"])
    assert (flag.code, flag.severity, flag.status) == ("DI-E401", "error", "open")
    assert flag.message == (
        "We couldn't read this document reliably. Re-run it or enter the values by hand."
    )
    job = await one(session, "SELECT status, progress, error FROM jobs")
    assert job.status == "failed" and job.progress == 1.0
    assert (
        job.error
        == "We couldn't use pay_stub_2026-09-27.pdf: the document could not be read reliably."
    )

    # Re-running only the later stages, with a working extractor, clears it.
    await run(body, s3_storage, session_factory, stages=["extract", "validate", "ready"])

    assert (await document(session, doc["id"])).status == "needs_review"
    flags = {(f.code, f.status): f for f in await flags_of(session, doc["id"])}
    assert flags[("DI-E401", "resolved")].reason == "read successfully"
    assert ("DI-CHK-02", "open") in flags


async def test_a_classify_failure_is_flagged_too(
    docs_client: httpx.AsyncClient,
    session: AsyncSession,
    s3_storage: Storage,
    session_factory: async_sessionmaker[AsyncSession],
    rendered: Rendered,
) -> None:
    body = await upload_files(docs_client, rendered, [STUB])
    [doc] = body["documents"]
    await run(body, s3_storage, session_factory, classifier=Failing())
    assert (await document(session, doc["id"])).status == "failed"
    assert [f.code for f in await flags_of(session, doc["id"])] == ["DI-E401"]
    assert await rows(session, "SELECT 1 FROM extraction_runs") == []


# --- safe to run twice, and each stage on its own --------------------------------------------


async def test_running_the_whole_pipeline_twice_changes_nothing_that_matters(
    docs_client: httpx.AsyncClient,
    session: AsyncSession,
    s3_storage: Storage,
    session_factory: async_sessionmaker[AsyncSession],
    rendered: Rendered,
) -> None:
    body = await upload_files(docs_client, rendered, [STUB])
    [doc] = body["documents"]
    extractor = Counting(FakeExtractor())

    await run(body, s3_storage, session_factory, extractor=extractor)
    first = (
        await rows(session, "SELECT count(*) AS n FROM fields WHERE document_id = :d", d=doc["id"])
    )[0].n
    await run(body, s3_storage, session_factory, extractor=extractor)

    # A repeated delivery makes no second model call and no second run, field or flag.
    assert extractor.calls == 1
    runs = await rows(
        session, "SELECT active FROM extraction_runs WHERE document_id = :d", d=doc["id"]
    )
    assert [r.active for r in runs] == [True]
    assert (
        await rows(session, "SELECT count(*) AS n FROM fields WHERE document_id = :d", d=doc["id"])
    )[0].n == first
    assert [(f.code, f.status) for f in await flags_of(session, doc["id"])] == [
        ("DI-CHK-02", "open")
    ]
    assert (await document(session, doc["id"])).status == "needs_review"
    assert (await one(session, "SELECT attempts FROM jobs")).attempts == 2


async def test_a_forced_extract_makes_a_new_run_and_keeps_the_old_one_as_history(
    docs_client: httpx.AsyncClient,
    session: AsyncSession,
    s3_storage: Storage,
    session_factory: async_sessionmaker[AsyncSession],
    rendered: Rendered,
) -> None:
    body = await upload_files(docs_client, rendered, [STUB])
    [doc] = body["documents"]
    await run(body, s3_storage, session_factory)
    first = (await one(session, "SELECT id FROM extraction_runs")).id

    await run(
        body,
        s3_storage,
        session_factory,
        stages=["extract", "validate", "ready"],
        force_extract=True,
    )

    runs = {
        r.id: r.active
        for r in await rows(
            session, "SELECT id, active FROM extraction_runs WHERE document_id = :d", d=doc["id"]
        )
    }
    assert len(runs) == 2 and runs[first] is False  # the first run stays, inactive
    assert list(runs.values()).count(True) == 1  # exactly one run is active
    old_flags = await rows(
        session,
        "SELECT fl.status, fl.reason FROM flags fl JOIN fields f ON f.id = fl.entity_id "
        "WHERE f.run_id = :r",
        r=first,
    )
    assert [(f.status, f.reason) for f in old_flags] == [
        ("resolved", "superseded by a newer extraction")
    ]
    assert [(f.code, f.status) for f in await flags_of(session, doc["id"], only_open=True)] == [
        ("DI-CHK-02", "open")
    ]  # the new run's own flag
    job = await one(session, "SELECT progress, stage FROM jobs")
    assert (job.progress, job.stage) == (1.0, "ready")  # 3 stages of 1 document


async def test_validate_and_ready_can_run_alone_and_change_nothing(
    docs_client: httpx.AsyncClient,
    session: AsyncSession,
    s3_storage: Storage,
    session_factory: async_sessionmaker[AsyncSession],
    rendered: Rendered,
) -> None:
    body = await upload_files(docs_client, rendered, [AUGUST])
    [doc] = body["documents"]
    await run(body, s3_storage, session_factory)
    before = [(f.code, f.status, f.message) for f in await flags_of(session, doc["id"])]

    await run(body, s3_storage, session_factory, stages=["validate", "ready"])

    assert [(f.code, f.status, f.message) for f in await flags_of(session, doc["id"])] == before
    assert (await document(session, doc["id"])).status == "needs_review"


async def test_a_type_a_person_set_is_never_overwritten_or_sent_to_a_model(
    docs_client: httpx.AsyncClient,
    session: AsyncSession,
    s3_storage: Storage,
    session_factory: async_sessionmaker[AsyncSession],
    rendered: Rendered,
) -> None:
    body = await upload_files(docs_client, rendered, [STUB])
    [doc] = body["documents"]
    await session.execute(
        sa.text(
            "UPDATE documents SET doc_type = 'pay_stub', doc_type_source = 'user' WHERE id = :d"
        ),
        {"d": doc["id"]},
    )
    classifier = Counting(FakeClassifier())

    await run(body, s3_storage, session_factory, classifier=classifier)

    assert classifier.calls == 0
    d = await document(session, doc["id"])
    assert (d.status, d.doc_type, d.doc_type_source) == ("needs_review", "pay_stub", "user")


# --- what a person's decision does to the flags ----------------------------------------------


async def test_a_flag_a_person_overrode_stays_overridden_when_the_checks_run_again(
    docs_client: httpx.AsyncClient,
    session: AsyncSession,
    s3_storage: Storage,
    session_factory: async_sessionmaker[AsyncSession],
    rendered: Rendered,
    user_id: uuid.UUID,
) -> None:
    body = await upload_files(docs_client, rendered, [STUB])
    [doc] = body["documents"]
    await run(body, s3_storage, session_factory)
    await session.execute(
        sa.text(
            "UPDATE flags SET status = 'overridden', resolved_by = :u, reason = 'checked the stub' "
            "WHERE code = 'DI-CHK-02'"
        ),
        {"u": user_id},
    )

    await run(body, s3_storage, session_factory, stages=["validate", "ready"])

    [flag] = await flags_of(session, doc["id"])
    assert (flag.status, flag.resolved_by, flag.reason) == (
        "overridden",
        user_id,
        "checked the stub",
    )
    # Nothing is left for a person, so the document is reviewed.
    assert (await document(session, doc["id"])).status == "reviewed"


async def test_a_flag_the_system_closed_reopens_if_its_check_fails_again(
    docs_client: httpx.AsyncClient,
    session: AsyncSession,
    s3_storage: Storage,
    session_factory: async_sessionmaker[AsyncSession],
    rendered: Rendered,
) -> None:
    body = await upload_files(docs_client, rendered, [STUB])
    [doc] = body["documents"]
    await run(body, s3_storage, session_factory)
    await session.execute(
        sa.text(
            "UPDATE flags SET status = 'resolved', reason = 'check now passes' "
            "WHERE code = 'DI-CHK-02'"
        )
    )

    await run(body, s3_storage, session_factory, stages=["validate", "ready"])

    [flag] = await flags_of(session, doc["id"])
    assert (flag.status, flag.reason) == ("open", None)


async def test_a_low_certainty_value_needs_review_even_without_a_flag(
    docs_client: httpx.AsyncClient,
    session: AsyncSession,
    s3_storage: Storage,
    session_factory: async_sessionmaker[AsyncSession],
    rendered: Rendered,
) -> None:
    class UnsureAboutTheEmployer(FakeExtractor):
        async def extract(self, doc_type: str, lines: Sequence[DocLine]) -> ExtractionOutcome:
            out = await super().extract(doc_type, lines)
            employer = out.fields["employer_name"]
            out.fields["employer_name"] = ExtractedField(employer.value, employer.lines, "low")
            return out

    body = await upload_files(
        docs_client,
        rendered,
        ["angela_whitfield/pay_stub_2026-06-30.pdf"],
        case=ANGELA,
        role=Role.LM_SPECIALIST,
    )
    [doc] = body["documents"]
    await run(body, s3_storage, session_factory, extractor=UnsureAboutTheEmployer())

    assert await flags_of(session, doc["id"], only_open=True) == []
    assert (
        await document(session, doc["id"])
    ).status == "needs_review"  # FSD 4.4: low needs review
    low = await one(
        session,
        "SELECT certainty FROM fields WHERE document_id = :d AND name = 'employer_name'",
        d=doc["id"],
    )
    assert low.certainty == "low"


async def test_a_required_value_the_reader_missed_is_an_empty_row_and_a_flag(
    docs_client: httpx.AsyncClient,
    session: AsyncSession,
    s3_storage: Storage,
    session_factory: async_sessionmaker[AsyncSession],
    rendered: Rendered,
) -> None:
    class MissesNetPay(FakeExtractor):
        async def extract(self, doc_type: str, lines: Sequence[DocLine]) -> ExtractionOutcome:
            out = await super().extract(doc_type, lines)
            del out.fields["net_pay_current"]
            return out

    body = await upload_files(docs_client, rendered, [STUB])
    [doc] = body["documents"]
    await run(body, s3_storage, session_factory, extractor=MissesNetPay())

    net = await one(
        session,
        "SELECT value, normalized_value, original_value, certainty, line_refs FROM fields "
        "WHERE document_id = :d AND name = 'net_pay_current'",
        d=doc["id"],
    )
    assert tuple(net) == (None, None, None, "low", [])
    by_code = {(f.code, f.field): f for f in await flags_of(session, doc["id"])}
    assert (
        by_code[("DI-W604", "net_pay_current")].message == "Net pay wasn't found in this document."
    )
    assert by_code[("DI-CHK-02", None)].severity == "info"  # cannot check, not a silent pass
    assert (await document(session, doc["id"])).status == "needs_review"


# --- the real classify task, through Arindam's own gateway and fake adapter ------------------


def classify_reply(doc_type: str = "pay_stub", **fields: object) -> AdapterResponse:
    body = {"doc_type": doc_type, "certainty": "high", "justification_line_ids": ["p1-L4"]}
    body.update(fields)
    return AdapterResponse(text=json.dumps(body), input_tokens=120, output_tokens=25)


async def test_the_pipeline_runs_through_the_real_classify_task(
    docs_client: httpx.AsyncClient,
    session: AsyncSession,
    s3_storage: Storage,
    session_factory: async_sessionmaker[AsyncSession],
    rendered: Rendered,
) -> None:
    adapter = FakeAdapter([classify_reply(justification_line_ids=["p1-L4", "p9-L9"])])
    classifier = LlmClassifier(gateway=Gateway({"fake": adapter}, fake_config()))
    body = await upload_files(docs_client, rendered, [STUB])
    [doc] = body["documents"]

    await run(body, s3_storage, session_factory, classifier=classifier)

    d = await document(session, doc["id"])
    assert (d.status, d.doc_type, d.doc_type_source) == ("needs_review", "pay_stub", "ai")
    # Arindam's prompt was rendered with numbered lines, and the file name was never sent.
    [request] = adapter.requests
    sent = request.messages[0].content
    assert "p1-L4: EARNINGS STATEMENT" in sent and "pay_stub_2026-09-27" not in sent
    assert "untrusted data" in (request.system or "")
    # The call is audited with its provider and model, and a cited line that was not there.
    event = await one(
        session, "SELECT after FROM audit_events WHERE action = 'document.classified'"
    )
    assert event.after["provider"] == "fake" and event.after["model"] == "fake-model"
    assert event.after["unknown_line_ids"] == ["p9-L9"]


async def test_the_real_classify_task_that_is_unsure_asks_for_a_choice(
    docs_client: httpx.AsyncClient,
    session: AsyncSession,
    s3_storage: Storage,
    session_factory: async_sessionmaker[AsyncSession],
    rendered: Rendered,
) -> None:
    adapter = FakeAdapter([classify_reply("bank_statement", certainty="medium")])
    classifier = LlmClassifier(gateway=Gateway({"fake": adapter}, fake_config()))
    body = await upload_files(docs_client, rendered, [STUB])
    [doc] = body["documents"]
    await run(body, s3_storage, session_factory, classifier=classifier)

    assert (await document(session, doc["id"])).status == "type_needed"
    assert [f.code for f in await flags_of(session, doc["id"])] == ["DI-W501"]


async def test_a_gateway_error_from_the_real_classify_task_is_flagged(
    docs_client: httpx.AsyncClient,
    session: AsyncSession,
    s3_storage: Storage,
    session_factory: async_sessionmaker[AsyncSession],
    rendered: Rendered,
) -> None:
    adapter = FakeAdapter(
        [classify_reply(doc_type="passport"), classify_reply(doc_type="passport")]
    )
    classifier = LlmClassifier(gateway=Gateway({"fake": adapter}, fake_config()))
    body = await upload_files(docs_client, rendered, [STUB])
    [doc] = body["documents"]
    await run(body, s3_storage, session_factory, classifier=classifier)

    # His gateway retried once on the schema failure, then raised; the pipeline flags it.
    assert len(adapter.requests) == 2
    assert (await document(session, doc["id"])).status == "failed"
    assert [f.code for f in await flags_of(session, doc["id"])] == ["DI-E401"]


async def test_daniels_stub_through_the_real_classify_and_extract_tasks(
    docs_client: httpx.AsyncClient,
    session: AsyncSession,
    s3_storage: Storage,
    session_factory: async_sessionmaker[AsyncSession],
    rendered: Rendered,
) -> None:
    # Both model calls go through Arindam's gateway (a fake provider answers). The result is
    # flattened by LlmExtractor, stored, and checked in code: the same single net pay flag as the
    # rule-based reader gives, plus the per-line hours, rate and year to date income will use.
    classifier = LlmClassifier(
        gateway=Gateway({"fake": FakeAdapter([classify_reply()])}, fake_config())
    )
    extractor, adapter = extractor_for(daniel_pay_stub_reply())
    body = await upload_files(docs_client, rendered, [STUB])
    [doc] = body["documents"]

    await run(body, s3_storage, session_factory, classifier=classifier, extractor=extractor)

    job = await one(session, "SELECT status, error FROM jobs")
    assert (job.status, job.error) == ("succeeded", None)
    d = await document(session, doc["id"])
    assert (d.status, d.doc_type, d.doc_type_source) == ("needs_review", "pay_stub", "ai")
    run_row = await one(
        session,
        "SELECT provider, model, prompt_id FROM extraction_runs WHERE document_id = :d",
        d=doc["id"],
    )
    assert tuple(run_row) == (
        "fake",
        "fake-model",
        "extract@1",
    )  # the gateway's, not the rule-based
    assert len(adapter.requests) == 1

    stored = {
        r.name: (r.value, r.normalized_value)
        for r in await rows(
            session,
            "SELECT name, value, normalized_value FROM fields WHERE document_id = :d",
            d=doc["id"],
        )
    }
    assert stored["earnings_001_hours"] == ("80.00", "80.00")
    assert stored["earnings_001_rate"] == ("34.50", "34.50")
    assert stored["earnings_002_ytd"] == ("3,897.10", "3897.10")
    assert stored["net_pay_current"] == ("2,083.61", "2083.61")

    [flag] = await flags_of(session, doc["id"], only_open=True)
    assert (flag.field, flag.code, flag.message) == (
        "net_pay_current",
        "DI-CHK-02",
        NET_PAY_MESSAGE,
    )

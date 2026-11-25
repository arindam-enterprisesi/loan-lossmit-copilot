"""The credit report analysis in the database (Feature Design 4): gather, compute, store, read.

``app.services.credit`` does the arithmetic (pure). This module reads the newest usable credit
report of the case as the pipeline stored it (fields numbered ``score_NNN_*``, ``tradeline_NNN_*``
and ``inquiry_NNN_*``, a person's corrections included), runs the analysis, and stores the result as
a new ``credit`` run: scores, tradelines and inquiries with the report lines they came from, every
metric as a calculation with its working, and every risk as a flag linked to its report line.

No model is called here: the only AI use in Feature 4 is the extraction that reads the report. The
report is simulated; nothing is sent to a bureau.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.enums import AnalysisFeature, AnalysisStatus, JobStatus
from app.db.models import (
    AnalysisRun,
    Calculation,
    CreditInquiry,
    CreditScore,
    Flag,
    Job,
    Tradeline,
)
from app.services import audit
from app.services import flags as flag_service
from app.services.analysis_config import AnalysisConfig, get_analysis_config
from app.services.calculations import percent
from app.services.case_facts import DocFacts, FieldFact, load_case_documents
from app.services.config_versions import record_config_versions
from app.services.credit import (
    CreditInputs,
    CreditOutcome,
    InquiryIn,
    LateFact,
    ScoreIn,
    SummaryFacts,
    TradelineIn,
    analyze,
    severity_label,
    slug,
    summarize,
)
from app.services.documents import UploadFailedError
from app.services.income import flag_entity_id
from app.services.pipeline import cause_chain
from app.services.queue import CREDIT_FUNCTION, JobQueue
from app.services.security import CurrentUser

logger = logging.getLogger(__name__)

CREDIT_JOB_KIND = "credit_analysis"
FAILED_MESSAGE = "The credit report analysis could not be completed."
FLAG_FEATURE = "credit"
FLAG_ENTITY = "credit_check"
CREDIT_REPORT = "credit_report"
ALERT_CODE = "CR-W105"


def _now() -> datetime:
    return datetime.now(UTC)


# --- starting a run -------------------------------------------------------------------------


async def start_run(
    session: AsyncSession, queue: JobQueue, user: CurrentUser, case_id: uuid.UUID
) -> tuple[AnalysisRun, Job]:
    """Record the request, then queue it. Commits, because the job is queued only after the rows."""
    job = Job(kind=CREDIT_JOB_KIND, case_id=case_id, status=JobStatus.QUEUED)
    session.add(job)
    await session.flush()
    run = AnalysisRun(
        case_id=case_id,
        feature=AnalysisFeature.CREDIT,
        status=AnalysisStatus.QUEUED,
        job_id=job.id,
        started_at=_now(),  # set here, not by now(): runs made in one transaction must still order
        created_by=uuid.UUID(user.id),
    )
    session.add(run)
    await session.flush()
    await audit.record(
        session,
        actor_id=uuid.UUID(user.id),
        role=user.role.value,
        action="credit.run_requested",
        entity_type="analysis_run",
        entity_id=run.id,
        case_id=case_id,
        after={"job_id": str(job.id)},
    )
    await session.commit()
    try:
        await queue.enqueue(CREDIT_FUNCTION, str(job.id), str(run.id), job_id=str(job.id))
    except Exception as exc:
        logger.warning("queueing job %s failed: %s", job.id, type(exc).__name__)
        job.status = JobStatus.FAILED
        job.error = "The analysis was saved but could not be queued."
        run.status = AnalysisStatus.FAILED
        run.finished_at = _now()
        await session.commit()
        raise UploadFailedError(
            "queue_unavailable", "The analysis was saved but could not be queued. Please try again."
        ) from exc
    await session.refresh(job)
    await session.refresh(run)
    return run, job


# --- reading the case's credit report ---------------------------------------------------------


def _newest_report(documents: Sequence[DocFacts]) -> DocFacts | None:
    found = [d for d in documents if d.doc_type == CREDIT_REPORT and d.usable]
    return max(found, key=lambda d: (d.created_at, d.id.int)) if found else None


Row = dict[str, FieldFact]


def _text(row: Row, part: str) -> str | None:
    fact = row.get(part)
    return fact.text if fact else None


def _amount(doc: DocFacts, row: Row, part: str) -> Decimal | None:
    fact = row.get(part)
    return doc.amount(fact.name) if fact else None


def _day(doc: DocFacts, row: Row, part: str) -> date | None:
    fact = row.get(part)
    return doc.day(fact.name) if fact else None


def _count(doc: DocFacts, row: Row, part: str) -> int:
    fact = row.get(part)
    value = doc.number(fact.name) if fact else None
    return int(value) if value is not None else 0


def read_report(documents: Sequence[DocFacts]) -> CreditInputs:
    """The newest credit report as the analysis reads it. Empty inputs when there is none."""
    doc = _newest_report(documents)
    if doc is None:
        return CreditInputs()
    scores: list[ScoreIn] = []
    for row in doc.rows("score_").values():
        bureau, value = row.get("bureau"), row.get("value")
        parsed = doc.number(value.name) if value else None
        if bureau is None or not bureau.text or parsed is None:
            continue
        refs = tuple(dict.fromkeys([*bureau.lines, *(value.lines if value else ())]))
        scores.append(ScoreIn(bureau.text, int(parsed), refs))
    tradelines: list[TradelineIn] = []
    for number, row in doc.rows("tradeline_").items():
        creditor = row.get("creditor")
        if creditor is None or not creditor.text:
            continue
        refs = tuple(dict.fromkeys(ref for fact in row.values() for ref in fact.lines))

        tradelines.append(
            TradelineIn(
                number=number,
                creditor=creditor.text,
                account_type=(_text(row, "account_type") or "other").lower(),
                ownership=_text(row, "ownership"),
                opened_on=_day(doc, row, "open_date"),
                status=_text(row, "status"),
                balance=_amount(doc, row, "balance"),
                credit_limit=_amount(doc, row, "credit_limit"),
                monthly_payment=_amount(doc, row, "monthly_payment"),
                past_due=_amount(doc, row, "past_due"),
                late_30=_count(doc, row, "late_30"),
                late_60=_count(doc, row, "late_60"),
                late_90=_count(doc, row, "late_90"),
                last_late_on=_day(doc, row, "most_recent_late"),
                remarks=_text(row, "remarks") or "",
                lines=refs,
            )
        )
    inquiries: list[InquiryIn] = []
    for number, row in doc.rows("inquiry_").items():
        creditor, when = row.get("creditor"), row.get("date")
        if creditor is None or not creditor.text:
            continue
        refs = tuple(dict.fromkeys([*creditor.lines, *(when.lines if when else ())]))
        inquiries.append(
            InquiryIn(number, creditor.text, doc.day(when.name) if when else None, refs)
        )
    alerts_text = doc.text("alerts")
    alerts = tuple(
        part.strip()
        for part in (alerts_text or "").replace("\n", ";").split(";")
        if part.strip() and part.strip().lower() not in {"none", "no alerts", "n/a"}
    )
    return CreditInputs(
        document_id=doc.id,
        report_date=doc.day("report_date"),
        scores=tuple(scores),
        tradelines=tuple(tradelines),
        inquiries=tuple(inquiries),
        alerts=alerts,
        alert_lines=doc.lines_of("alerts"),
    )


# --- storing ---------------------------------------------------------------------------------


async def persist(
    session: AsyncSession,
    run: AnalysisRun,
    inputs: CreditInputs,
    outcome: CreditOutcome,
    cfg: AnalysisConfig,
) -> None:
    """Store an analysis. Safe to run again for the same run: it replaces what was stored."""
    uses = cfg.uses()
    await record_config_versions(session, uses)
    run.config_versions = cfg.snapshot(uses)

    for model in (CreditInquiry, Tradeline, CreditScore, Calculation):
        await session.execute(sa.delete(model).where(model.run_id == run.id))
    await session.execute(
        sa.delete(Flag).where(
            Flag.feature == FLAG_FEATURE, Flag.evidence["run_id"].astext == str(run.id)
        )
    )
    for calc in outcome.calcs:
        session.add(
            Calculation(
                run_id=run.id,
                case_id=run.case_id,
                name=calc.name,
                value=calc.value,
                unit=calc.unit,
                formula=calc.formula,
                inputs=dict(calc.inputs),
                working=calc.working,
                evidence=list(calc.evidence) or None,
            )
        )
    representative = outcome.representative_bureau
    for score in inputs.scores:
        session.add(
            CreditScore(
                run_id=run.id,
                case_id=run.case_id,
                document_id=inputs.document_id,
                bureau=score.bureau,
                score=score.value,
                is_representative=score.bureau == representative,
                line_refs=list(score.lines),
            )
        )
    stored: dict[int, Tradeline] = {}
    for result in outcome.tradelines:
        t = result.tradeline
        row = Tradeline(
            run_id=run.id,
            case_id=run.case_id,
            document_id=inputs.document_id,
            position=t.number,
            creditor=t.creditor,
            account_type=t.account_type,
            ownership=t.ownership,
            opened_on=t.opened_on,
            status=t.status,
            balance=t.balance,
            credit_limit=t.credit_limit,
            monthly_payment=t.monthly_payment,
            past_due=t.past_due,
            late_30=t.late_30,
            late_60=t.late_60,
            late_90=t.late_90,
            last_late_on=t.last_late_on,
            remarks=t.remarks,
            line_refs=list(t.lines),
            utilization_over_review_level=result.utilization_over_review_level,
            late_in_lookback=result.late_in_lookback,
            derogatory=result.derogatory,
        )
        session.add(row)
        stored[t.number] = row
    await session.flush()
    for item in outcome.inquiries:
        matched = stored.get(item.matched.number) if item.matched else None
        session.add(
            CreditInquiry(
                run_id=run.id,
                case_id=run.case_id,
                document_id=inputs.document_id,
                position=item.inquiry.number,
                creditor=item.inquiry.creditor,
                inquired_on=item.inquiry.on,
                in_window=item.in_window,
                matched_tradeline_id=matched.id if matched else None,
                line_refs=list(item.inquiry.lines),
            )
        )
    for found in outcome.flags:
        await flag_service.raise_flag(
            session,
            case_id=run.case_id,
            entity_type=FLAG_ENTITY,
            entity_id=flag_entity_id(run.id, found.code, found.key),
            code=found.code,
            severity=found.severity,
            message=found.message,
            evidence={
                "run_id": str(run.id),
                "check": found.key,
                "refs": [e for e in found.evidence if e.get("document_id")],
                # The alerts themselves, so the summary can be rebuilt from what is stored.
                **({"alerts": list(inputs.alerts)} if found.code == ALERT_CODE else {}),
            },
            feature=FLAG_FEATURE,
        )
    await session.flush()


async def run_credit_job(
    factory: async_sessionmaker[AsyncSession],
    job_id: uuid.UUID,
    run_id: uuid.UUID,
    *,
    config: AnalysisConfig | None = None,
) -> None:
    """What the worker runs: analyse the case's credit report and store the result."""
    cfg = config or get_analysis_config()
    async with factory() as session:
        job, run = await session.get(Job, job_id), await session.get(AnalysisRun, run_id)
        if job is None or run is None:
            raise LookupError(f"credit job {job_id} or run {run_id} does not exist")
        job.status, job.stage, job.progress = JobStatus.RUNNING, "collect", 0.1
        job.attempts += 1
        run.status = AnalysisStatus.RUNNING
        await session.commit()
        try:
            inputs = read_report(await load_case_documents(session, run.case_id))
            job.stage, job.progress = "calculate", 0.5
            await session.commit()
            outcome = analyze(inputs, cfg)
            job.stage, job.progress = "save", 0.8
            await persist(session, run, inputs, outcome, cfg)
            run.status, run.finished_at = AnalysisStatus.SUCCEEDED, _now()
            job.status, job.stage, job.progress, job.error = JobStatus.SUCCEEDED, "done", 1.0, None
            await audit.record(
                session,
                actor_id=None,
                role="worker",
                action="credit.analysed",
                entity_type="analysis_run",
                entity_id=run.id,
                case_id=run.case_id,
                after={
                    "representative_score": str(outcome.representative.value)
                    if outcome.representative
                    else None,
                    "tradelines": len(outcome.tradelines),
                    "flags": len(outcome.flags),
                    "config_versions": run.config_versions,
                },
            )
            await session.commit()
        except Exception as exc:
            await session.rollback()
            logger.warning("credit analysis failed run=%s: %s", run_id, cause_chain(exc))
            job, run = await session.get(Job, job_id), await session.get(AnalysisRun, run_id)
            if job is not None and run is not None:
                job.status, job.error = JobStatus.FAILED, FAILED_MESSAGE
                run.status, run.finished_at = AnalysisStatus.FAILED, _now()
                await session.commit()


# --- reading a run ----------------------------------------------------------------------------


@dataclass
class CreditView:
    run: AnalysisRun
    scores: list[CreditScore]
    tradelines: list[Tradeline]
    inquiries: list[CreditInquiry]
    calculations: list[Calculation]
    flags: list[Flag]

    def calc(self, name: str) -> Calculation | None:
        return next((c for c in self.calculations if c.name == name), None)

    def version_string(self) -> str:
        versions = self.run.config_versions
        return f"thresholds@{versions['thresholds']['version']}" if "thresholds" in versions else ""


async def latest_run(session: AsyncSession, case_id: uuid.UUID) -> AnalysisRun | None:
    """The newest credit run of the case, in any state."""
    return await session.scalar(
        sa.select(AnalysisRun)
        .where(AnalysisRun.case_id == case_id, AnalysisRun.feature == AnalysisFeature.CREDIT)
        .order_by(AnalysisRun.started_at.desc(), AnalysisRun.id.desc())
        .limit(1)
    )


async def load_view(session: AsyncSession, run: AnalysisRun) -> CreditView:
    async def rows(model: Any, *order: Any) -> list[Any]:
        query = sa.select(model).where(model.run_id == run.id).order_by(*order)
        return list((await session.execute(query)).scalars().all())

    flags = list(
        (
            await session.execute(
                sa.select(Flag)
                .where(Flag.feature == FLAG_FEATURE, Flag.evidence["run_id"].astext == str(run.id))
                .order_by(Flag.code, Flag.id)
            )
        )
        .scalars()
        .all()
    )
    return CreditView(
        run=run,
        scores=await rows(CreditScore, CreditScore.bureau),
        tradelines=await rows(Tradeline, Tradeline.position),
        inquiries=await rows(CreditInquiry, CreditInquiry.position),
        calculations=await rows(Calculation, Calculation.created_at, Calculation.name),
        flags=flags,
    )


def summary_from_view(view: CreditView) -> list[str]:
    """The template summary, rebuilt from what is stored (the same words ``analyze`` produced)."""
    by_id = {t.id: t for t in view.tradelines}
    late: list[LateFact] = []
    over: list[tuple[str, str]] = []
    for row in view.tradelines:
        key = slug(row.creditor)
        months = view.calc(f"months_since_last_late_{key}")
        if row.late_in_lookback and months is not None:
            line = TradelineIn(
                number=row.position,
                creditor=row.creditor,
                account_type=row.account_type,
                late_30=row.late_30,
                late_60=row.late_60,
                late_90=row.late_90,
            )
            count = row.late_30 + row.late_60 + row.late_90
            late.append(LateFact(row.creditor, severity_label(line), count, int(months.value)))
        utilization = view.calc(f"utilization_{key}")
        if row.utilization_over_review_level and utilization is not None:
            over.append((row.creditor, percent(utilization.value)))
    alerts = next(
        (
            tuple(f.evidence.get("alerts", ()))
            for f in view.flags
            if f.code == ALERT_CODE and f.evidence
        ),
        (),
    )
    inquiries = tuple(
        (
            i.creditor,
            by_id[i.matched_tradeline_id].creditor if i.matched_tradeline_id in by_id else None,
        )
        for i in view.inquiries
        if i.in_window
    )
    derogatory = tuple(t.creditor for t in view.tradelines if t.derogatory)
    return summarize(SummaryFacts(alerts, tuple(late), tuple(over), inquiries, derogatory))

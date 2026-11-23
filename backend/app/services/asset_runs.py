"""Asset and liability runs: start one, run it in the worker, store it, read it, correct it.

``app.services.assets`` does the analysis (pure). This module is the database side:

* ``start_run`` records the request (a run and a job) and queues it;
* ``run_asset_job`` is what the worker runs: read the statements' lines, label the ones not yet
  labelled, analyse, store the figures, debts and flags, and finish the job;
* ``load_view`` reads a stored run back;
* ``reclassify_transaction``, ``set_deposit_sourced`` and ``set_obligation_counted`` are a person's
  changes. Each recalculates at once with no model call, keeps what the system decided beside the
  person's change, and writes an audit event (rule 6);
* ``what_if`` recomputes the ratios on a stored run with changes applied, without storing anything.

Labels belong to the statement line, not to a run (``transactions`` is keyed by document and line),
so a new run never relabels a line a person changed. A person's include or exclude of a debt is
carried into later runs by creditor name.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.enums import (
    AnalysisFeature,
    AnalysisStatus,
    CategorySource,
    JobStatus,
    ObligationSource,
    TransactionCategory,
    TransactionDirection,
)
from app.db.models import (
    AnalysisRun,
    Calculation,
    Case,
    Document,
    ExtractionRun,
    Flag,
    Job,
    LoanScenario,
    Obligation,
    Transaction,
)
from app.db.models import Field as FieldRow
from app.llm.tasks import TransactionInput
from app.services import audit, income_runs
from app.services import flags as flag_service
from app.services.analysis_config import AnalysisConfig, get_analysis_config
from app.services.assets import (
    AssetInputs,
    AssetOutcome,
    IncomeInput,
    LiabilityInput,
    ObligationResult,
    StatementInput,
    StubInput,
    TxnInput,
    WhatIfChanges,
    WhatIfResult,
    _same_name,
    analyze,
)
from app.services.assets import what_if as compute_what_if
from app.services.calculations import money
from app.services.case_facts import DocFacts, load_case_documents
from app.services.config_versions import record_config_versions
from app.services.documents import UploadFailedError
from app.services.income import flag_entity_id
from app.services.loan_scenarios import as_input
from app.services.normalize import parse_amount, parse_date
from app.services.pipeline import cause_chain
from app.services.queue import ASSET_FUNCTION, JobQueue
from app.services.security import CurrentUser
from app.services.transaction_labels import TransactionLabeller, get_labeller

logger = logging.getLogger(__name__)

ASSET_JOB_KIND = "asset_analysis"
FAILED_MESSAGE = "The asset and liability analysis could not be completed."
FLAG_FEATURE = "assets"
FLAG_ENTITY = "asset_check"
PAYROLL_MATCH = "payroll_match"
LARGE_DEPOSIT = "large_deposit"


class AssetError(Exception):
    """A request the analysis cannot honour. ``status`` and ``code`` are for the API."""

    def __init__(self, status: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status, self.code, self.message = status, code, message


def _now() -> datetime:
    return datetime.now(UTC)


# --- starting a run -------------------------------------------------------------------------


async def start_run(
    session: AsyncSession, queue: JobQueue, user: CurrentUser, case_id: uuid.UUID
) -> tuple[AnalysisRun, Job]:
    """Record the request, then queue it. Commits, because the job is queued only after the rows."""
    job = Job(kind=ASSET_JOB_KIND, case_id=case_id, status=JobStatus.QUEUED)
    session.add(job)
    await session.flush()
    run = AnalysisRun(
        case_id=case_id,
        feature=AnalysisFeature.ASSETS,
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
        action="assets.run_requested",
        entity_type="analysis_run",
        entity_id=run.id,
        case_id=case_id,
        after={"job_id": str(job.id)},
    )
    await session.commit()
    try:
        await queue.enqueue(ASSET_FUNCTION, str(job.id), str(run.id), job_id=str(job.id))
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


# --- reading the case's documents -----------------------------------------------------------


def _statement_rows(doc: DocFacts) -> list[tuple[str, Any, str, Decimal]]:
    """(line_ref, date, description, signed amount) for each transaction row of a statement."""
    out: list[tuple[str, Any, str, Decimal]] = []
    for row in doc.rows("txn_").values():
        description, day, amount = row.get("description"), row.get("date"), row.get("amount")
        if not (description and day and amount):
            continue
        posted, signed = parse_date(day.text), parse_amount(amount.text)
        refs = description.lines or day.lines or amount.lines
        if posted is None or signed is None or not refs or not description.text:
            continue
        out.append((refs[0], posted, description.text, signed))
    return out


def _stubs(documents: Sequence[DocFacts], cfg: AnalysisConfig) -> list[StubInput]:
    out: list[StubInput] = []
    for doc in documents:
        if doc.doc_type != "pay_stub" or not doc.usable:
            continue
        frequency = cfg.income.frequency_for(doc.text("pay_frequency"))
        spec = frequency[1] if frequency else None
        out.append(
            StubInput(
                document_id=doc.id,
                employer=doc.text("employer_name") or "",
                pay_date=doc.day("pay_date"),
                # The gap between pay dates, from the middle of the configured range (a monthly
                # stub is 28 to 31 days): projected dates are then checked against a few days.
                period_days=(spec.min_days + spec.max_days) // 2 if spec else None,
                net_pay=doc.amount("net_pay_current"),
                lines=doc.lines_of("net_pay_current"),
            )
        )
    return out


def _liabilities(documents: Sequence[DocFacts]) -> list[LiabilityInput]:
    out: list[LiabilityInput] = []
    for doc in documents:
        if doc.doc_type != "credit_report" or not doc.usable:
            continue
        for row in doc.rows("tradeline_").values():
            creditor = row.get("creditor")
            if creditor is None or not creditor.text:
                continue
            refs = [ref for fact in row.values() for ref in fact.lines]
            payment, balance, kind = (
                row.get("monthly_payment"),
                row.get("balance"),
                row.get("account_type"),
            )
            out.append(
                LiabilityInput(
                    document_id=doc.id,
                    creditor=creditor.text,
                    kind=(kind.text or "other").lower() if kind else "other",
                    balance=parse_amount(balance.text) if balance else None,
                    monthly_payment=parse_amount(payment.text) if payment else None,
                    lines=tuple(dict.fromkeys(refs)),
                )
            )
    return out


async def _income(session: AsyncSession, case_id: uuid.UUID) -> IncomeInput | None:
    run = await income_runs.latest_run(session, case_id)
    if run is None or run.status != AnalysisStatus.SUCCEEDED:
        return None
    view = await income_runs.load_view(session, run)
    if view.candidate is None:
        return None
    left_out: dict[str, Decimal] = {}
    for part in view.components:
        if not part.included and part.monthly > 0:
            kind = part.component.value
            left_out[kind] = left_out.get(kind, Decimal(0)) + part.monthly
    return IncomeInput(view.candidate.value, left_out, income_runs.CANDIDATE)


async def _overrides(session: AsyncSession, case_id: uuid.UUID) -> dict[str, Obligation]:
    """A person's include or exclude of each debt, as the case's newest stored run holds it.

    A run carries the changes forward when it is stored (its debts keep who, when and why), so the
    newest run that has debts is the whole record. An older run's change that a person later undid
    is not read back.
    """
    newest = await session.scalar(
        sa.select(Obligation.run_id)
        .join(AnalysisRun, AnalysisRun.id == Obligation.run_id)
        .where(Obligation.case_id == case_id)
        .order_by(AnalysisRun.started_at.desc(), AnalysisRun.id.desc())
        .limit(1)
    )
    if newest is None:
        return {}
    rows = (
        (
            await session.execute(
                sa.select(Obligation).where(
                    Obligation.run_id == newest, Obligation.updated_by.is_not(None)
                )
            )
        )
        .scalars()
        .all()
    )
    return {row.creditor: row for row in rows}


# --- labelling ------------------------------------------------------------------------------


async def sync_transactions(
    session: AsyncSession,
    labeller: TransactionLabeller,
    case: Case,
    documents: Sequence[DocFacts],
) -> int:
    """Make ``transactions`` match the statements' lines and label the new ones (one call per
    statement). A line already labelled keeps its label, whoever gave it. Returns lines added."""
    employers = [s.employer for s in _stubs(documents, get_analysis_config()) if s.employer]
    added = 0
    for doc in documents:
        if doc.doc_type != "bank_statement" or not doc.usable:
            continue
        current = {ref: (day, text, amount) for ref, day, text, amount in _statement_rows(doc)}
        held = {
            row.line_ref: row
            for row in (
                await session.execute(
                    sa.select(Transaction).where(Transaction.document_id == doc.id)
                )
            ).scalars()
        }
        for ref, gone in held.items():
            if ref not in current and gone.updated_by is None:
                await session.delete(gone)  # the line is no longer in the statement's reading
        fresh: list[tuple[str, Any, str, Decimal]] = []
        for ref, (day, text, amount) in current.items():
            row = held.get(ref)
            if row is None:
                fresh.append((ref, day, text, amount))
                continue
            row.posted_on, row.description, row.amount = day, text, abs(amount)  # as read
            row.direction = (
                TransactionDirection.DEBIT if amount < 0 else TransactionDirection.CREDIT
            )
        if fresh:
            labels = await labeller.label(
                [
                    TransactionInput(ref, day.isoformat(), text, f"{amount:f}")
                    for ref, day, text, amount in fresh
                ],
                borrower_names=case.borrower_names or [],
                employer_names=employers,
            )
            for (ref, day, text, amount), label in zip(fresh, labels, strict=True):
                session.add(
                    Transaction(
                        document_id=doc.id,
                        line_ref=ref,
                        account_last4=doc.text("account_last4"),
                        posted_on=day,
                        description=text,
                        amount=abs(amount),
                        direction=(
                            TransactionDirection.DEBIT
                            if amount < 0
                            else TransactionDirection.CREDIT
                        ),
                        category=TransactionCategory(label.category.value),
                        counterparty=label.counterparty,
                        category_source=CategorySource.AI,
                        needs_review=label.needs_review,
                    )
                )
                added += 1
    await session.flush()
    return added


# --- gathering the analysis' inputs ----------------------------------------------------------


async def gather(
    session: AsyncSession, case_id: uuid.UUID, cfg: AnalysisConfig, documents: Sequence[DocFacts]
) -> AssetInputs:
    case = await session.get(Case, case_id)
    held: dict[uuid.UUID, list[Transaction]] = {}
    ids = [d.id for d in documents if d.doc_type == "bank_statement"]
    if ids:
        for row in (
            await session.execute(sa.select(Transaction).where(Transaction.document_id.in_(ids)))
        ).scalars():
            held.setdefault(row.document_id, []).append(row)
    statements: list[StatementInput] = []
    for doc in documents:
        if doc.doc_type != "bank_statement" or not doc.usable:
            continue
        rows = sorted(held.get(doc.id, []), key=lambda r: (r.posted_on, r.line_ref))
        statements.append(
            StatementInput(
                document_id=doc.id,
                account_last4=doc.text("account_last4"),
                period_start=doc.period_start,
                period_end=doc.period_end,
                opening_balance=doc.amount("opening_balance"),
                closing_balance=doc.amount("closing_balance"),
                closing_lines=doc.lines_of("closing_balance"),
                transactions=tuple(
                    TxnInput(
                        id=r.id,
                        document_id=doc.id,
                        line_ref=r.line_ref,
                        account_last4=r.account_last4,
                        posted_on=r.posted_on,
                        description=r.description,
                        amount=r.amount,
                        direction=r.direction.value,
                        category=r.category.value,
                        counterparty=r.counterparty,
                        needs_review=r.needs_review,
                        sourced=r.sourced,
                    )
                    for r in rows
                ),
            )
        )
    scenario = await session.get(LoanScenario, case_id)
    overrides = await _overrides(session, case_id)
    return AssetInputs(
        statements=tuple(statements),
        stubs=tuple(_stubs(documents, cfg)),
        liabilities=tuple(_liabilities(documents)),
        scenario=as_input(scenario) if scenario else None,
        income=await _income(session, case_id),
        borrower_names=tuple(case.borrower_names or []) if case else (),
        obligation_overrides=tuple(
            (name, row.counts_toward_dti) for name, row in overrides.items()
        ),
    )


# --- storing a run --------------------------------------------------------------------------


async def _net_pay_fields(session: AsyncSession, case_id: uuid.UUID) -> dict[uuid.UUID, uuid.UUID]:
    rows = await session.execute(
        sa.select(FieldRow.document_id, FieldRow.id)
        .join(ExtractionRun, ExtractionRun.id == FieldRow.run_id)
        .join(Document, Document.id == FieldRow.document_id)
        .where(
            Document.case_id == case_id,
            ExtractionRun.active.is_(True),
            FieldRow.name == "net_pay_current",
        )
    )
    return {document_id: field_id for document_id, field_id in rows.all()}


async def persist(
    session: AsyncSession, run: AnalysisRun, outcome: AssetOutcome, cfg: AnalysisConfig
) -> None:
    """Store an analysis. Safe to run again for the same run: it replaces the figures and flags
    and updates the debts in place, so a debt keeps its id."""
    uses = cfg.uses()
    await record_config_versions(session, uses)
    run.config_versions = cfg.snapshot(uses)

    await session.execute(sa.delete(Calculation).where(Calculation.run_id == run.id))
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

    overrides = await _overrides(session, run.case_id)
    old = {
        (o.creditor.lower(), o.kind): o
        for o in (
            await session.execute(sa.select(Obligation).where(Obligation.run_id == run.id))
        ).scalars()
    }
    kept: set[tuple[str, str]] = set()
    for found in outcome.obligations:
        key = (found.creditor.lower(), found.kind)
        kept.add(key)
        system = found.system_counts if found.system_counts is not None else found.counts_toward_dti
        by = next((o for name, o in overrides.items() if _same_name(found.creditor, name)), None)
        person = by if by is not None and found.system_counts is not None else None
        row = old.get(key)
        if row is None:
            row = Obligation(run_id=run.id, case_id=run.case_id)
            session.add(row)
        row.creditor, row.kind = found.creditor, found.kind
        row.monthly_payment, row.balance = found.monthly_payment, found.balance
        row.source = ObligationSource(found.source)
        row.counts_toward_dti, row.reason = found.counts_toward_dti, found.reason
        row.original_counts_toward_dti = system
        row.review_reason = person.review_reason if person else None
        row.updated_by = person.updated_by if person else None
        row.updated_at = person.updated_at if person else None
    for key, row in old.items():
        if key not in kept:
            await session.delete(row)

    fields = await _net_pay_fields(session, run.case_id)
    for t in outcome.transactions:
        if t.input.id is None:
            continue
        stored = await session.get(Transaction, t.input.id)
        if stored is not None:
            stored.payroll_match_field_id = (
                fields.get(t.payroll_match.stub_document_id) if t.payroll_match else None
            )
    for flag in outcome.flags:
        await flag_service.raise_flag(
            session,
            case_id=run.case_id,
            entity_type=FLAG_ENTITY,
            entity_id=flag_entity_id(run.id, flag.code, flag.key),
            code=flag.code,
            severity=flag.severity,
            message=flag.message,
            evidence={
                "run_id": str(run.id),
                "check": flag.key,
                "refs": list(flag.evidence),
                "working": flag.working,
            },
            feature=FLAG_FEATURE,
        )
    await session.flush()


async def recompute(session: AsyncSession, run: AnalysisRun, cfg: AnalysisConfig) -> AssetOutcome:
    """Analyse the stored labels again and store the result. No model is called."""
    documents = await load_case_documents(session, run.case_id)
    outcome = analyze(await gather(session, run.case_id, cfg, documents), cfg)
    await persist(session, run, outcome, cfg)
    return outcome


# --- the worker -----------------------------------------------------------------------------


async def run_asset_job(
    factory: async_sessionmaker[AsyncSession],
    job_id: uuid.UUID,
    run_id: uuid.UUID,
    *,
    config: AnalysisConfig | None = None,
    labeller: TransactionLabeller | None = None,
) -> None:
    """What the worker runs: label the statements' new lines, analyse, store the result."""
    cfg = config or get_analysis_config()
    async with factory() as session:
        job, run = await session.get(Job, job_id), await session.get(AnalysisRun, run_id)
        if job is None or run is None:
            raise LookupError(f"asset job {job_id} or run {run_id} does not exist")
        job.status, job.stage, job.progress = JobStatus.RUNNING, "collect", 0.1
        job.attempts += 1
        run.status = AnalysisStatus.RUNNING
        await session.commit()
        try:
            case = await session.get(Case, run.case_id)
            documents = await load_case_documents(session, run.case_id)
            job.stage, job.progress = "label", 0.3
            await session.commit()
            added = 0
            if case is not None:
                added = await sync_transactions(
                    session, labeller or get_labeller(), case, documents
                )
            job.stage, job.progress = "calculate", 0.6
            await session.commit()
            outcome = analyze(await gather(session, run.case_id, cfg, documents), cfg)
            job.stage, job.progress = "save", 0.8
            await persist(session, run, outcome, cfg)
            run.status, run.finished_at = AnalysisStatus.SUCCEEDED, _now()
            job.status, job.stage, job.progress, job.error = JobStatus.SUCCEEDED, "done", 1.0, None
            counted = outcome.calc("monthly_obligations")
            await audit.record(
                session,
                actor_id=None,
                role="worker",
                action="assets.analysed",
                entity_type="analysis_run",
                entity_id=run.id,
                case_id=run.case_id,
                after={
                    "transactions_labelled": added,
                    "obligations": len(outcome.obligations),
                    "monthly_obligations": str(counted.value) if counted else None,
                    "flags": len(outcome.flags),
                    "config_versions": run.config_versions,
                },
            )
            await session.commit()
        except Exception as exc:
            await session.rollback()
            logger.warning("asset analysis failed run=%s: %s", run_id, cause_chain(exc))
            job, run = await session.get(Job, job_id), await session.get(AnalysisRun, run_id)
            if job is not None and run is not None:
                job.status, job.error = JobStatus.FAILED, FAILED_MESSAGE
                run.status, run.finished_at = AnalysisStatus.FAILED, _now()
                await session.commit()


# --- reading a run --------------------------------------------------------------------------


@dataclass
class AssetView:
    run: AnalysisRun
    transactions: list[Transaction]
    obligations: list[Obligation]
    calculations: list[Calculation]
    flags: list[Flag]

    def version_string(self) -> str:
        return income_runs.version_string(self.run.config_versions)

    def calc(self, name: str) -> Calculation | None:
        return next((c for c in self.calculations if c.name == name), None)

    def calc_for_line(self, name: str, document_id: uuid.UUID, line_ref: str) -> Calculation | None:
        """The per-line figure (payroll match or large deposit) for one statement line."""
        for c in self.calculations:
            first = (c.evidence or [{}])[0]
            if (
                c.name == name
                and first.get("document_id") == str(document_id)
                and line_ref in first.get("line_ids", [])
            ):
                return c
        return None


async def latest_run(session: AsyncSession, case_id: uuid.UUID) -> AnalysisRun | None:
    """The newest asset run of the case, in any state."""
    return await session.scalar(
        sa.select(AnalysisRun)
        .where(AnalysisRun.case_id == case_id, AnalysisRun.feature == AnalysisFeature.ASSETS)
        .order_by(AnalysisRun.started_at.desc(), AnalysisRun.id.desc())
        .limit(1)
    )


async def load_view(session: AsyncSession, run: AnalysisRun) -> AssetView:
    transactions = list(
        (
            await session.execute(
                sa.select(Transaction)
                .join(Document, Document.id == Transaction.document_id)
                .where(Document.case_id == run.case_id)
                .order_by(Transaction.posted_on, Transaction.line_ref, Transaction.id)
            )
        )
        .scalars()
        .all()
    )
    obligations = list(
        (
            await session.execute(
                sa.select(Obligation)
                .where(Obligation.run_id == run.id)
                .order_by(sa.func.lower(Obligation.creditor), Obligation.id)
            )
        )
        .scalars()
        .all()
    )
    calculations = list(
        (
            await session.execute(
                sa.select(Calculation)
                .where(Calculation.run_id == run.id)
                .order_by(Calculation.created_at, Calculation.name, Calculation.id)
            )
        )
        .scalars()
        .all()
    )
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
    return AssetView(run, transactions, obligations, calculations, flags)


# --- a person's changes ---------------------------------------------------------------------


async def _current_run(
    session: AsyncSession, case_id: uuid.UUID, run: AnalysisRun | None
) -> AnalysisRun:
    newest = await latest_run(session, case_id)
    if run is None or run.case_id != case_id:
        raise AssetError(404, "not_found", "Not found")
    if newest is None or newest.id != run.id:
        raise AssetError(409, "stale_analysis", "A newer analysis has replaced this one.")
    if run.status != AnalysisStatus.SUCCEEDED:
        raise AssetError(409, "analysis_not_ready", "The analysis has not finished.")
    return run


async def _own_transaction(
    session: AsyncSession, case_id: uuid.UUID, transaction_id: uuid.UUID
) -> Transaction:
    row = await session.scalar(
        sa.select(Transaction)
        .join(Document, Document.id == Transaction.document_id)
        .where(Transaction.id == transaction_id, Document.case_id == case_id)
    )
    if row is None:
        raise AssetError(404, "not_found", "Transaction not found")
    return row


async def _finish(session: AsyncSession, run: AnalysisRun, cfg: AnalysisConfig) -> AssetView:
    await recompute(session, run, cfg)
    await session.commit()
    return await load_view(session, run)


async def reclassify_transaction(
    session: AsyncSession,
    user: CurrentUser,
    case_id: uuid.UUID,
    transaction_id: uuid.UUID,
    *,
    category: TransactionCategory,
    reason: str,
    cfg: AnalysisConfig | None = None,
) -> AssetView:
    """Give a line a different category, with a reason. The system's label stays in
    ``original_category``; the analysis is recalculated at once."""
    cfg = cfg or get_analysis_config()
    run = await _current_run(session, case_id, await latest_run(session, case_id))
    row = await _own_transaction(session, case_id, transaction_id)
    if category == row.category:
        raise AssetError(422, "no_change", "The line already has that category.")
    before = {"category": row.category.value, "needs_review": row.needs_review}
    if row.original_category is None:
        row.original_category = row.category
    row.category, row.category_source = category, CategorySource.USER
    row.needs_review, row.review_reason = False, reason
    row.updated_by, row.updated_at = uuid.UUID(user.id), _now()
    await session.flush()
    await audit.record(
        session,
        actor_id=uuid.UUID(user.id),
        role=user.role.value,
        action="assets.transaction_reclassified",
        entity_type="transaction",
        entity_id=row.id,
        case_id=case_id,
        before=before,
        after={
            "category": category.value,
            "original_category": row.original_category.value,
            "amount": money(row.amount),
            "line": f"{row.document_id}:{row.line_ref}",
        },
        reason=reason,
    )
    return await _finish(session, run, cfg)


async def set_deposit_sourced(
    session: AsyncSession,
    user: CurrentUser,
    case_id: uuid.UUID,
    transaction_id: uuid.UUID,
    *,
    sourced: bool,
    note: str,
    cfg: AnalysisConfig | None = None,
) -> AssetView:
    """Mark a deposit as sourced, with a note (not verification: Feature Design 3.1), or undo it."""
    cfg = cfg or get_analysis_config()
    run = await _current_run(session, case_id, await latest_run(session, case_id))
    row = await _own_transaction(session, case_id, transaction_id)
    if row.direction != TransactionDirection.CREDIT:
        raise AssetError(422, "not_a_deposit", "Only a deposit can be marked as sourced.")
    before = {"sourced": row.sourced, "sourced_note": row.sourced_note}
    row.sourced = sourced
    row.sourced_note = note if sourced else None
    row.review_reason = note
    row.updated_by, row.updated_at = uuid.UUID(user.id), _now()
    await session.flush()
    await audit.record(
        session,
        actor_id=uuid.UUID(user.id),
        role=user.role.value,
        action="assets.deposit_sourced" if sourced else "assets.deposit_unsourced",
        entity_type="transaction",
        entity_id=row.id,
        case_id=case_id,
        before=before,
        after={
            "sourced": sourced,
            "sourced_note": row.sourced_note,
            "amount": money(row.amount),
            "line": f"{row.document_id}:{row.line_ref}",
        },
        reason=note,
    )
    return await _finish(session, run, cfg)


async def set_obligation_counted(
    session: AsyncSession,
    user: CurrentUser,
    case_id: uuid.UUID,
    obligation_id: uuid.UUID,
    *,
    counts: bool,
    reason: str,
    cfg: AnalysisConfig | None = None,
) -> AssetView:
    """Include a debt in the DTI or leave it out, with a reason. The system's decision stays in
    ``original_counts_toward_dti``; the ratios are recalculated at once and later runs keep it."""
    cfg = cfg or get_analysis_config()
    run = await _current_run(session, case_id, await latest_run(session, case_id))
    row = await session.get(Obligation, obligation_id)
    if row is None or row.run_id != run.id:
        raise AssetError(404, "not_found", "Obligation not found")
    before = {"counts_toward_dti": row.counts_toward_dti}
    before_total = (await load_view(session, run)).calc("monthly_obligations")
    row.counts_toward_dti = counts
    row.review_reason = reason
    row.updated_by, row.updated_at = uuid.UUID(user.id), _now()
    await session.flush()
    await recompute(session, run, cfg)
    view = await load_view(session, run)
    total = view.calc("monthly_obligations")
    await audit.record(
        session,
        actor_id=uuid.UUID(user.id),
        role=user.role.value,
        action="assets.obligation_included" if counts else "assets.obligation_excluded",
        entity_type="obligation",
        entity_id=obligation_id,
        case_id=case_id,
        before={
            **before,
            "monthly_obligations": money(before_total.value) if before_total else None,
        },
        after={
            "counts_toward_dti": counts,
            "system_counts_toward_dti": row.original_counts_toward_dti,
            "creditor": row.creditor,
            "monthly_payment": money(row.monthly_payment),
            "monthly_obligations": money(total.value) if total else None,
            "working": total.working if total else None,
        },
        reason=reason,
    )
    await session.commit()
    return await load_view(session, run)


# --- what if --------------------------------------------------------------------------------


async def what_if(
    session: AsyncSession,
    case_id: uuid.UUID,
    changes: WhatIfChanges,
    *,
    cfg: AnalysisConfig | None = None,
) -> WhatIfResult | None:
    """The ratios of the case's newest finished run with ``changes`` applied (for the Researcher).
    Nothing is stored. None when the case has no finished asset analysis."""
    cfg = cfg or get_analysis_config()
    run = await latest_run(session, case_id)
    if run is None or run.status != AnalysisStatus.SUCCEEDED:
        return None
    view = await load_view(session, run)
    scenario = await session.get(LoanScenario, case_id)
    assets = view.calc("documented_assets")
    return compute_what_if(
        scenario=as_input(scenario) if scenario else None,
        income=await _income(session, case_id),
        obligations=[
            ObligationResult(
                creditor=o.creditor,
                kind=o.kind,
                monthly_payment=o.monthly_payment,
                balance=o.balance,
                source=o.source.value,
                counts_toward_dti=o.counts_toward_dti,
                reason=o.reason,
            )
            for o in view.obligations
        ],
        documented_assets=assets.value if assets else None,
        changes=changes,
        version=view.version_string(),
        review_level=cfg.thresholds.dti_review_level.value,
    )

"""The loss mitigation rules in the database (Feature Design 8.4, step 4: code decides first).

``rules_engine`` does the arithmetic and decides every condition (pure). This module gathers what
the rules read from the case, stores the result as a new ``lm_recommendation`` run (the waterfall,
the lender view and every figure with its working), and carries overrides forward.

What the rules read:

* the hardship profile's duration and intent, **as a person confirmed them** (an unconfirmed reading
  is not used; Feature Design 8.2 step 1);
* the hardship budget's surplus (on the rule set's basis) and documented gross monthly income;
* the mortgage statement's balance, regular payment and past-due amount, with the loan record (the
  simulated servicing record) as the fallback and the only source of months delinquent.

A run is created only when its result is complete, so the newest run is always one with a waterfall.
Overrides are a person's reasoned changes to a condition's status: they carry to the next run by
condition id, with the system's own status shown beside them (rule 6), and the statuses recompute.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Sequence
from datetime import datetime
from decimal import Decimal
from typing import Any

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.enums import (
    AnalysisFeature,
    AnalysisStatus,
    JobStatus,
    WaterfallOption,
    WaterfallStatus,
)
from app.db.models import (
    AnalysisRun,
    Calculation,
    Job,
    LenderView,
    LoanRecord,
    WaterfallResult,
)
from app.services import audit, budget_runs, hardship, hardship_runs, report_writer
from app.services.calculations import Calc, Evidence, cents
from app.services.case_facts import DocFacts, load_case_documents
from app.services.config_versions import record_config_versions
from app.services.documents import UploadFailedError
from app.services.pipeline import cause_chain
from app.services.queue import RECOMMENDATION_FUNCTION, JobQueue
from app.services.rules_config import LoadedRuleSet, RuleSetConfig, get_rule_set
from app.services.rules_engine import Fact, Judgement, RuleInputs, RulesOutcome, evaluate
from app.services.security import CurrentUser
from app.services.waterfall_status import override_summary, recompute

logger = logging.getLogger(__name__)

RECOMMENDATION_JOB_KIND = "lm_recommendation"
FAILED_MESSAGE = "The rules could not be applied to this case."
MORTGAGE_STATEMENT = "mortgage_statement"


# --- reading the case ------------------------------------------------------------------------


def _newest(documents: Sequence[DocFacts], doc_type: str) -> DocFacts | None:
    found = [d for d in documents if d.doc_type == doc_type and d.usable]
    return max(found, key=lambda d: (d.created_at, d.id.int)) if found else None


def _from_statement(doc: DocFacts | None, name: str) -> Fact | None:
    value = doc.amount(name) if doc else None
    if doc is None or value is None:
        return None
    evidence: Evidence = {
        "document_id": str(doc.id),
        "field": name,
        "line_ids": list(doc.lines_of(name)),
    }
    return Fact(value, (evidence,))


def _from_record(record: LoanRecord | None, column: str) -> Fact | None:
    if record is None:
        return None
    value = Decimal(getattr(record, column))
    evidence: Evidence = {
        "loan_record_id": str(record.id),
        "field": column,
        "label": "simulated servicing record",
    }
    return Fact(value, (evidence,))


def _from_calc(row: Calculation | None) -> Fact | None:
    if row is None:
        return None
    evidence: Evidence = {"calculation_id": str(row.id), "name": row.name}
    # The column keeps six decimals for ratios; money is whole cents.
    value = cents(Decimal(row.value)) if row.unit == "usd" else Decimal(row.value)
    return Fact(value, (evidence, *(row.evidence or ())))


def _judgement(profile: Any, item: str) -> Judgement:
    if profile is None:
        return Judgement(None, False)
    value, confirmed = hardship.effective_values(profile)[item]
    data: dict[str, Any] = getattr(profile, item)
    evidence: Evidence = {
        "hardship_profile_id": str(profile.id),
        "item": item,
        "document_id": str(profile.document_id) if profile.document_id else None,
        "line_ids": list(data.get("lines") or []),
    }
    return Judgement(value, confirmed, (evidence,))


async def gather_inputs(
    session: AsyncSession, case_id: uuid.UUID, rules: RuleSetConfig
) -> RuleInputs:
    hardship_view = await hardship_runs.latest(session, case_id)
    profile = hardship_view.profile if hardship_view else None
    budget = await budget_runs.load_view(session, hardship_view.run) if hardship_view else None
    documents = await load_case_documents(session, case_id)
    statement = _newest(documents, MORTGAGE_STATEMENT)
    record = await session.scalar(sa.select(LoanRecord).where(LoanRecord.case_id == case_id))
    basis = rules.settings.surplus_basis.value
    return RuleInputs(
        duration=_judgement(profile, "duration"),
        intent=_judgement(profile, "intent"),
        surplus=_from_calc(budget.calc(f"surplus_{basis}") if budget else None),
        gross_monthly_income=_from_calc(
            budget.calc("documented_gross_monthly_income") if budget else None
        ),
        arrears=_from_statement(statement, "past_due_amount")
        or _from_record(record, "arrears_amount"),
        contractual_payment=_from_statement(statement, "regular_monthly_payment")
        or _from_record(record, "monthly_payment"),
        unpaid_balance=_from_statement(statement, "unpaid_principal_balance")
        or _from_record(record, "unpaid_balance"),
        months_delinquent=_from_record(record, "months_delinquent"),
    )


# --- carrying overrides forward ---------------------------------------------------------------


async def carried_overrides(session: AsyncSession, case_id: uuid.UUID) -> dict[str, dict[str, Any]]:
    """The overrides on the case's newest recommendation, by condition id."""
    newest = await session.scalar(
        sa.select(AnalysisRun.id)
        .where(
            AnalysisRun.case_id == case_id, AnalysisRun.feature == AnalysisFeature.LM_RECOMMENDATION
        )
        .order_by(AnalysisRun.started_at.desc(), AnalysisRun.id.desc())
        .limit(1)
    )
    if newest is None:
        return {}
    rows = (
        await session.execute(
            sa.select(WaterfallResult.conditions).where(WaterfallResult.run_id == newest)
        )
    ).scalars()
    return {c["id"]: c["override"] for conditions in rows for c in conditions if c.get("override")}


def _with_overrides(
    outcome: RulesOutcome, carried: dict[str, dict[str, Any]]
) -> list[tuple[str, str, list[dict[str, Any]]]]:
    """Each option as (rules' status, status after overrides, conditions with overrides applied).
    An override stays only while it differs from what the rules now find: if the rules caught up,
    the person's reason is no longer needed and the system status shows alone."""
    plain = [o.conditions for o in outcome.options]
    marked: list[list[dict[str, Any]]] = []
    for conditions in plain:
        row = []
        for c in conditions:
            c = dict(c)
            held = carried.get(c["id"])
            if held and not c.get("derived") and held["status"] != c["status"]:
                c["override"] = dict(held)
            row.append(c)
        marked.append(row)
    effective = recompute(marked)
    return [
        (o.status, status, conditions)
        for o, (status, conditions) in zip(outcome.options, effective, strict=True)
    ]


# --- storing ---------------------------------------------------------------------------------


def _store_calc(run: AnalysisRun, calc: Calc) -> Calculation:
    return Calculation(
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


async def run_recommendation_rules(
    session: AsyncSession,
    case_id: uuid.UUID,
    *,
    user_id: uuid.UUID | None = None,
    job_id: uuid.UUID | None = None,
    rule_set: LoadedRuleSet | None = None,
) -> AnalysisRun:
    """Apply the rule set to the case and store a new recommendation run. This is step 4 of
    Arindam's graph and what ``POST /cases/{id}/lm-recommendation`` runs. It flushes and the caller
    commits. No model is called."""
    loaded = rule_set or get_rule_set()
    await record_config_versions(session, [loaded.use()])
    inputs = await gather_inputs(session, case_id, loaded.config)
    outcome = evaluate(loaded.config, inputs)
    carried = await carried_overrides(session, case_id)
    run = await report_writer.start_run(
        session,
        case_id,
        AnalysisFeature.LM_RECOMMENDATION,
        created_by=user_id,
        config_versions=loaded.snapshot(),
        job_id=job_id,
    )
    planned = _with_overrides(outcome, carried)
    for number, (system, status, conditions) in enumerate(planned, start=1):
        overridden, reason, by, at = override_summary(conditions)
        session.add(
            WaterfallResult(
                run_id=run.id,
                rule_set_version=loaded.config.version,
                order_no=number,
                option=WaterfallOption(outcome.options[number - 1].option),
                status=WaterfallStatus(status),
                original_status=WaterfallStatus(system),
                conditions=conditions,
                overridden=overridden,
                override_reason=reason,
                overridden_by=uuid.UUID(by) if by else None,
                overridden_at=datetime.fromisoformat(at) if at else None,
            )
        )
    stored: dict[str, Calculation] = {}
    for calc in outcome.calcs:
        row = _store_calc(run, calc)
        session.add(row)
        stored[calc.name] = row
    await session.flush()
    if outcome.lender_figures:
        by_name = {c.name: c.value for c in outcome.calcs}
        session.add(
            LenderView(
                run_id=run.id,
                foreclosure_loss=by_name["foreclosure_loss"],
                modification_cost=by_name["modification_cost"],
                advantage=by_name["modification_advantage"],
                settings=outcome.lender_settings,
                calculation_ids=[stored[name].id for name in outcome.lender_figures],
            )
        )
    await report_writer.finish_run(session, run, AnalysisStatus.SUCCEEDED)
    await audit.record(
        session,
        actor_id=None,
        role="worker",
        action="lm.rules_evaluated",
        entity_type="analysis_run",
        entity_id=run.id,
        case_id=case_id,
        after={
            "rule_set": loaded.snapshot()["rule_set"],
            "options": {
                o.option: status for o, (_, status, _) in zip(outcome.options, planned, strict=True)
            },
            "overrides_carried": sorted(
                c["id"] for _, _, conditions in planned for c in conditions if c.get("override")
            ),
            "lender_view": bool(outcome.lender_figures),
        },
    )
    return run


# --- the request and the worker --------------------------------------------------------------


async def start_recommendation(
    session: AsyncSession, queue: JobQueue, user: CurrentUser, case_id: uuid.UUID
) -> Job:
    """Record the request, then queue it. Commits, because the job is queued only after the rows."""
    job = Job(kind=RECOMMENDATION_JOB_KIND, case_id=case_id, status=JobStatus.QUEUED)
    session.add(job)
    await session.flush()
    await audit.record(
        session,
        actor_id=uuid.UUID(user.id),
        role=user.role.value,
        action="lm.rules_requested",
        entity_type="job",
        entity_id=job.id,
        case_id=case_id,
    )
    await session.commit()
    try:
        await queue.enqueue(RECOMMENDATION_FUNCTION, str(job.id), user.id, job_id=str(job.id))
    except Exception as exc:
        logger.warning("queueing job %s failed: %s", job.id, type(exc).__name__)
        job.status = JobStatus.FAILED
        job.error = "The request was saved but could not be queued."
        await session.commit()
        raise UploadFailedError(
            "queue_unavailable", "The request was saved but could not be queued. Please try again."
        ) from exc
    await session.refresh(job)
    return job


async def run_recommendation_job(
    factory: async_sessionmaker[AsyncSession],
    job_id: uuid.UUID,
    user_id: uuid.UUID | None,
    *,
    rule_set: LoadedRuleSet | None = None,
) -> None:
    """What the worker runs: apply the rules and store the result (plain code, no model)."""
    async with factory() as session:
        job = await session.get(Job, job_id)
        if job is None or job.case_id is None:
            raise LookupError(f"recommendation job {job_id} does not exist")
        case_id = job.case_id
        job.status, job.stage, job.progress = JobStatus.RUNNING, "rules", 0.3
        job.attempts += 1
        await session.commit()
        try:
            run = await run_recommendation_rules(
                session, case_id, user_id=user_id, job_id=job_id, rule_set=rule_set
            )
            job.stage, job.progress = "agents", 0.6
            await session.commit()
            # The agents explain the rules' result on the same run (Feature Design 8.5). They
            # never change it, and their failure leaves the waterfall as it is.
            from app.agents.jobs import run_lm_after_rules

            await run_lm_after_rules(session, run)
            job.status, job.stage, job.progress, job.error = JobStatus.SUCCEEDED, "done", 1.0, None
            await session.commit()
        except Exception as exc:
            await session.rollback()
            logger.warning("recommendation rules failed job=%s: %s", job_id, cause_chain(exc))
            failed = await session.get(Job, job_id)
            if failed is not None:
                failed.status, failed.error = JobStatus.FAILED, FAILED_MESSAGE
                await session.commit()

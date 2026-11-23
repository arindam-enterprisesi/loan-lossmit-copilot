"""The hardship budget in the database: gather a case's documents, compute, store, read, adjust.

``app.services.budget`` does the arithmetic (pure). This module is the database side. A budget
belongs to a hardship run (the run that stored the letter's profile), so "latest" is the newest
hardship run, like everything else on the case. Recomputing replaces the stored figures and keeps
the budget lines in place, so a line keeps its id and a person's adjustment of it.

An adjustment is a person marking part of an observed amount as one-off, with a reason. The
statements' own amount stays beside it (``observed_amount`` is never changed), the measures update
at once with no model call, and an audit event records who, when and why (rule 6). A later reading
of the letter is a new run; the adjustments carry over to it by budget line.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.enums import TransactionDirection
from app.db.models import (
    AnalysisRun,
    BudgetLine,
    Calculation,
    Case,
    Flag,
    HardshipProfile,
    Transaction,
)
from app.prompts.schemas.hardship import load_hardship_config
from app.services import audit
from app.services import flags as flag_service
from app.services.analysis_config import AnalysisConfig, get_analysis_config
from app.services.asset_runs import sync_transactions
from app.services.budget import (
    Balance,
    BudgetInputs,
    BudgetOutcome,
    DebitLine,
    Figure,
    LetterFacts,
    StatedRow,
    StubPay,
    compute_budget,
    hours_change,
)
from app.services.calculations import money
from app.services.case_facts import DocFacts, load_case_documents
from app.services.config_versions import record_config_versions
from app.services.income import flag_entity_id
from app.services.security import CurrentUser
from app.services.transaction_labels import TransactionLabeller

FLAG_FEATURE = "budget"
FLAG_ENTITY = "budget_check"
APPLICATION, MORTGAGE_STATEMENT = "mortgage_assistance_application", "mortgage_statement"


class BudgetError(Exception):
    """A request the budget cannot honour. ``status`` and ``code`` are for the API."""

    def __init__(self, status: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status, self.code, self.message = status, code, message


def _now() -> datetime:
    return datetime.now(UTC)


# --- reading the case's documents ------------------------------------------------------------


def _newest(documents: Sequence[DocFacts], doc_type: str) -> DocFacts | None:
    found = [d for d in documents if d.doc_type == doc_type and d.usable]
    return max(found, key=lambda d: (d.created_at, d.id.int)) if found else None


def _stubs(documents: Sequence[DocFacts], cfg: AnalysisConfig) -> tuple[StubPay, ...]:
    out: list[StubPay] = []
    for doc in documents:
        if doc.doc_type != "pay_stub" or not doc.usable:
            continue
        frequency = cfg.income.frequency_for(doc.text("pay_frequency"))
        gross, net, pay_date = (
            doc.amount("gross_pay_current"),
            doc.amount("net_pay_current"),
            doc.day("pay_date"),
        )
        if frequency is None or gross is None or net is None or pay_date is None:
            continue
        out.append(
            StubPay(
                document_id=doc.id,
                pay_date=pay_date,
                gross=gross,
                net=net,
                periods_per_year=frequency[1].periods_per_year,
                gross_lines=doc.lines_of("gross_pay_current"),
                net_lines=doc.lines_of("net_pay_current"),
            )
        )
    return tuple(out)


def _rows(doc: DocFacts | None, prefix: str) -> tuple[StatedRow, ...]:
    if doc is None:
        return ()
    out: list[StatedRow] = []
    for row in doc.rows(prefix).values():
        description, amount = row.get("description"), row.get("amount")
        value = doc.amount(amount.name) if amount else None
        if description is None or not description.text or value is None:
            continue
        refs = tuple(dict.fromkeys([*description.lines, *(amount.lines if amount else ())]))
        out.append(StatedRow(doc.id, description.text, value, refs))
    return tuple(out)


def _balances(documents: Sequence[DocFacts]) -> tuple[Balance, ...]:
    """The newest statement's closing balance for each account."""
    newest: dict[str | None, DocFacts] = {}
    for doc in documents:
        if (
            doc.doc_type != "bank_statement"
            or not doc.usable
            or doc.amount("closing_balance") is None
        ):
            continue
        key = doc.text("account_last4")
        held = newest.get(key)
        if held is None or (doc.period_end or datetime.min.date()) >= (
            held.period_end or datetime.min.date()
        ):
            newest[key] = doc
    return tuple(
        Balance(d.id, key, d.amount("closing_balance") or Decimal(0), d.lines_of("closing_balance"))
        for key, d in sorted(newest.items(), key=lambda kv: kv[0] or "")
    )


def _figure(doc: DocFacts | None, name: str) -> Figure | None:
    value = doc.amount(name) if doc else None
    return Figure(value, doc.id, doc.lines_of(name)) if doc and value is not None else None


def effective(item: dict[str, object], key: str) -> object:
    """An item's value as the specialist confirmed it, else as read from the letter."""
    confirmation = item.get("confirmation")
    if isinstance(confirmation, dict):
        return confirmation.get("value")
    return item.get(key)


def _letter(profile: HardshipProfile | None) -> LetterFacts | None:
    if profile is None:
        return None
    reason = effective(profile.primary_reason, "category")
    intent = effective(profile.intent, "category")
    texts = [
        str(t)
        for t in (
            profile.primary_reason.get("quote"),
            profile.primary_reason.get("financial_effect"),
            profile.onset.get("quote"),
            *(e.get("quote") for e in profile.timeline),
            *(e.get("event") for e in profile.timeline),
        )
        if t
    ]
    return LetterFacts(
        str(reason) if reason else None, str(intent) if intent else None, hours_change(texts)
    )


async def _carried(session: AsyncSession, case_id: uuid.UUID) -> dict[str, BudgetLine]:
    """A person's adjustments, as the case's newest run that has budget lines holds them."""
    newest = await session.scalar(
        sa.select(BudgetLine.run_id)
        .join(AnalysisRun, AnalysisRun.id == BudgetLine.run_id)
        .where(AnalysisRun.case_id == case_id)
        .order_by(AnalysisRun.started_at.desc(), AnalysisRun.id.desc())
        .limit(1)
    )
    if newest is None:
        return {}
    rows = (
        await session.execute(
            sa.select(BudgetLine).where(
                BudgetLine.run_id == newest, BudgetLine.adjusted_amount.is_not(None)
            )
        )
    ).scalars()
    return {row.category: row for row in rows}


async def gather(
    session: AsyncSession,
    case_id: uuid.UUID,
    profile: HardshipProfile | None,
    cfg: AnalysisConfig,
    documents: Sequence[DocFacts],
    carried: dict[str, BudgetLine],
) -> BudgetInputs:
    statements = [d for d in documents if d.doc_type == "bank_statement" and d.usable]
    debits: list[DebitLine] = []
    if statements:
        rows = (
            await session.execute(
                sa.select(Transaction).where(
                    Transaction.document_id.in_([d.id for d in statements]),
                    Transaction.direction == TransactionDirection.DEBIT,
                )
            )
        ).scalars()
        debits = [
            DebitLine(r.document_id, r.line_ref, r.posted_on, r.amount, r.category.value)
            for r in rows
        ]
    application = _newest(documents, APPLICATION)
    mortgage = _newest(documents, MORTGAGE_STATEMENT)
    reasons = (
        tuple(
            row["reason"].text
            for row in application.rows("hardship_reasons_").values()
            if "reason" in row and row["reason"].text
        )
        if application
        else ()
    )
    return BudgetInputs(
        stubs=_stubs(documents, cfg),
        stated_expenses=_rows(application, "monthly_expenses_"),
        stated_income=_rows(application, "monthly_income_"),
        application_reasons=reasons,
        application_intent=application.text("intent") if application else None,
        has_statements=bool(statements),
        debits=tuple(debits),
        balances=_balances(documents),
        contractual_payment=_figure(mortgage, "regular_monthly_payment"),
        arrears=_figure(mortgage, "past_due_amount"),
        letter=_letter(profile),
        reason_keys={c.label.lower(): c.key for c in load_hardship_config().categories},
        adjustments={
            cat: (row.adjusted_amount, row.adjustment_reason or "")
            for cat, row in carried.items()
            if row.adjusted_amount is not None
        },
    )


# --- storing ---------------------------------------------------------------------------------


async def persist(
    session: AsyncSession,
    run: AnalysisRun,
    outcome: BudgetOutcome,
    cfg: AnalysisConfig,
    carried: dict[str, BudgetLine],
) -> None:
    """Store a budget. Safe to run again for the same run: it replaces the figures and flags and
    updates the lines in place, so a line keeps its id and its adjustment."""
    uses = cfg.uses()
    await record_config_versions(session, uses)
    run.config_versions = {**run.config_versions, **cfg.snapshot(uses)}

    await session.execute(
        sa.delete(Flag).where(
            Flag.feature == FLAG_FEATURE, Flag.evidence["run_id"].astext == str(run.id)
        )
    )
    calcs = [*outcome.calcs]
    for line in outcome.lines:
        calcs += [c for c in (line.stated_calc, line.observed_calc) if c is not None]
    # Update each figure in place by its name, so a figure keeps its id (a finding may cite it).
    stored = {
        c.name: c
        for c in (
            await session.execute(sa.select(Calculation).where(Calculation.run_id == run.id))
        ).scalars()
    }
    for calc in calcs:
        figure = stored.pop(calc.name, None)
        if figure is None:
            figure = Calculation(run_id=run.id, case_id=run.case_id, name=calc.name)
            session.add(figure)
        figure.value, figure.unit, figure.formula = calc.value, calc.unit, calc.formula
        figure.inputs, figure.working = dict(calc.inputs), calc.working
        figure.evidence = list(calc.evidence) or None
    for stale in stored.values():
        await session.delete(stale)
    held = {
        row.category: row
        for row in (
            await session.execute(sa.select(BudgetLine).where(BudgetLine.run_id == run.id))
        ).scalars()
    }
    for line in outcome.lines:
        row = held.pop(line.category, None)
        if row is None:
            row = BudgetLine(run_id=run.id, category=line.category)
            session.add(row)
        row.stated_amount, row.observed_amount, row.flagged = (
            line.stated,
            line.observed,
            line.flagged,
        )
        row.adjusted_amount, row.adjustment_reason = line.adjusted, line.adjustment_reason
        person = carried.get(line.category) if line.adjusted is not None else None
        if person is not None and person.run_id != run.id:
            row.updated_by, row.updated_at = person.updated_by, person.updated_at
        elif line.adjusted is None:
            row.updated_by = row.updated_at = None
    for gone in held.values():
        await session.delete(gone)
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
                "refs": list(found.evidence),
                "working": found.working,
            },
            feature=FLAG_FEATURE,
        )
    await session.flush()


async def compute_for_run(
    session: AsyncSession,
    run: AnalysisRun,
    *,
    cfg: AnalysisConfig | None = None,
    labeller: TransactionLabeller | None = None,
) -> BudgetOutcome:
    """Compute and store the budget of a hardship run from the case's documents. With a labeller,
    the statements' new lines are labelled first (one call per statement); without one, the labels
    already stored are used, so no model is called. The caller commits."""
    cfg = cfg or get_analysis_config()
    documents = await load_case_documents(session, run.case_id)
    if labeller is not None:
        case = await session.get(Case, run.case_id)
        if case is not None:
            await sync_transactions(session, labeller, case, documents)
    profile = await session.scalar(
        sa.select(HardshipProfile).where(HardshipProfile.run_id == run.id)
    )
    carried = await _carried(session, run.case_id)
    inputs = await gather(session, run.case_id, profile, cfg, documents, carried)
    outcome = compute_budget(inputs, cfg)
    await persist(session, run, outcome, cfg, carried)
    return outcome


# --- reading ---------------------------------------------------------------------------------


@dataclass
class BudgetView:
    lines: list[BudgetLine]
    calculations: list[Calculation]
    flags: list[Flag]

    def calc(self, name: str) -> Calculation | None:
        return next((c for c in self.calculations if c.name == name), None)


async def load_view(session: AsyncSession, run: AnalysisRun) -> BudgetView:
    lines = list(
        (await session.execute(sa.select(BudgetLine).where(BudgetLine.run_id == run.id)))
        .scalars()
        .all()
    )
    order = {
        name: n for n, name in enumerate(get_analysis_config().thresholds.budget_categories.value)
    }
    lines.sort(key=lambda row: (order.get(row.category, len(order)), row.category))
    calculations = list(
        (
            await session.execute(
                sa.select(Calculation)
                .where(Calculation.run_id == run.id)
                .order_by(Calculation.name)
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
                .order_by(Flag.code, Flag.message, Flag.id)
            )
        )
        .scalars()
        .all()
    )
    return BudgetView(lines, calculations, flags)


# --- a person adjusts a line -----------------------------------------------------------------


async def adjust_line(
    session: AsyncSession,
    user: CurrentUser,
    case_id: uuid.UUID,
    run: AnalysisRun,
    line_id: uuid.UUID,
    *,
    amount: Decimal | None,
    reason: str,
    cfg: AnalysisConfig | None = None,
) -> BudgetView:
    """Set (or clear, with ``amount`` None) the observed amount a person counts for a line, with a
    reason. The statements' amount stays beside it; the measures update at once, with no model."""
    cfg = cfg or get_analysis_config()
    row = await session.get(BudgetLine, line_id)
    if row is None or row.run_id != run.id:
        raise BudgetError(404, "not_found", "Budget line not found")
    if amount is not None and row.observed_amount is None:
        raise BudgetError(
            422, "no_observed_amount", "There are no bank statements to adjust this line against."
        )
    before_view = await load_view(session, run)
    before_surplus = before_view.calc("surplus_observed")
    before = {
        "adjusted_amount": money(row.adjusted_amount) if row.adjusted_amount is not None else None,
        "adjustment_reason": row.adjustment_reason,
        "observed_amount": money(row.observed_amount) if row.observed_amount is not None else None,
        "surplus_observed": money(before_surplus.value) if before_surplus else None,
    }
    actor = uuid.UUID(user.id)
    row.adjusted_amount = amount
    row.adjustment_reason = reason if amount is not None else None
    row.updated_by, row.updated_at = (actor, _now()) if amount is not None else (None, None)
    await session.flush()
    await compute_for_run(session, run, cfg=cfg)
    view = await load_view(session, run)
    after_surplus = view.calc("surplus_observed")
    await audit.record(
        session,
        actor_id=actor,
        role=user.role.value,
        action="budget.line_adjusted" if amount is not None else "budget.adjustment_cleared",
        entity_type="budget_line",
        entity_id=line_id,
        case_id=case_id,
        before=before,
        after={
            "category": row.category,
            "adjusted_amount": money(amount) if amount is not None else None,
            "observed_amount": money(row.observed_amount)
            if row.observed_amount is not None
            else None,
            "surplus_observed": money(after_surplus.value) if after_surplus else None,
            "working": after_surplus.working if after_surplus else None,
        },
        reason=reason,
    )
    await session.commit()
    return await load_view(session, run)

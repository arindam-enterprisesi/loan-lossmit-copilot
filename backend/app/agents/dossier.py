"""What the agents may know about a case, gathered in code from stored results (Feature Design 6.3).

The dossier is the only input the agents see: every stored calculation of the case's newest
successful run of each feature (with its working), the open flags those runs raised and the
document checks, the checklist items that are not satisfied, and for Pillar 2 the hardship profile
and the waterfall. Each item has a stable ``ref`` the Writer must cite, and every number the
reports may contain is one of the numbers in here (the Critic checks).
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.enums import AnalysisFeature, AnalysisStatus, FlagStatus
from app.db.models import AnalysisRun, Calculation, Case, Flag
from app.llm.checks import numbers_in
from app.services.completeness_runs import latest_view

UNDERWRITING_FEATURES = (AnalysisFeature.INCOME, AnalysisFeature.ASSETS, AnalysisFeature.CREDIT)
LM_FEATURES = (AnalysisFeature.HARDSHIP, AnalysisFeature.LM_RECOMMENDATION)


@dataclass(frozen=True)
class Fact:
    """One thing the agents may cite: ``assets.dti`` | DTI | 44.70% | (1,980.00 + 693.00) / ..."""

    ref: str
    label: str
    value: str
    working: str = ""
    evidence: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class FlagGroup:
    """Open flags with one code, from the newest runs (one finding each)."""

    code: str
    severity: str
    messages: tuple[str, ...]
    flag_ids: tuple[uuid.UUID, ...]
    refs: tuple[dict[str, Any], ...]


@dataclass
class Dossier:
    case_id: uuid.UUID
    case_ref: str
    pillar: str
    borrower: str
    facts: list[Fact] = field(default_factory=list)
    flags: list[FlagGroup] = field(default_factory=list)
    gaps: list[Fact] = field(default_factory=list)  # checklist items not satisfied
    extra: dict[str, Any] = field(default_factory=dict)  # hardship profile, waterfall

    def fact(self, ref: str) -> Fact | None:
        return next((f for f in self.facts if f.ref == ref), None)

    def refs(self) -> set[str]:
        return {f.ref for f in [*self.facts, *self.gaps]} | {g.code for g in self.flags}

    def allowed_numbers(self, *more: str) -> set[Decimal]:
        """Every number in the dossier, as code computed or the documents printed it."""
        texts: list[str] = [*more]
        for f in [*self.facts, *self.gaps]:
            texts += [f.label, f.value, f.working]
        for g in self.flags:
            texts += [g.code, *g.messages]
        texts.append(self.case_ref)
        return numbers_in(*texts)

    def render(self) -> str:
        """The dossier as the agents see it: one line per item, refs first."""
        rows = [
            f"- {f.ref} | {f.label} | {f.value}"
            + (f" | {f.working}" if f.working and f.working != f.value else "")
            for f in self.facts
        ]
        for g in self.flags:
            rows += [f"- flag {g.code} ({g.severity}) | {m}" for m in g.messages]
        rows += [f"- {f.ref} | {f.label} | {f.value}" for f in self.gaps]
        return "\n".join(rows)


def shown(value: Decimal, unit: str) -> str:
    """A stored figure as a person reads it: 9,226.32 / 44.70% / 9 months."""
    if unit == "ratio":
        return f"{(value * 100).quantize(Decimal('0.01')):,}%"
    if unit == "usd":
        return f"{value.quantize(Decimal('0.01')):,}"
    whole = (
        value.quantize(Decimal("1")) if value == value.to_integral_value() else value.normalize()
    )
    return f"{whole:,} {unit}" if unit not in ("match", "count") else f"{whole:,}"


async def newest_runs(
    session: AsyncSession, case_id: uuid.UUID, features: Iterable[AnalysisFeature]
) -> dict[AnalysisFeature, AnalysisRun]:
    found: dict[AnalysisFeature, AnalysisRun] = {}
    for feature in features:
        run = await session.scalar(
            sa.select(AnalysisRun)
            .where(
                AnalysisRun.case_id == case_id,
                AnalysisRun.feature == feature,
                AnalysisRun.status == AnalysisStatus.SUCCEEDED,
            )
            .order_by(AnalysisRun.started_at.desc(), AnalysisRun.id.desc())
            .limit(1)
        )
        if run is not None:
            found[feature] = run
    return found


async def build_dossier(
    session: AsyncSession,
    case_id: uuid.UUID,
    features: Iterable[AnalysisFeature],
    *,
    skip_codes: Iterable[str] = (),
) -> Dossier:
    case = await session.get(Case, case_id)
    if case is None:
        raise LookupError(f"case {case_id} does not exist")
    dossier = Dossier(
        case_id=case_id,
        case_ref=case.case_ref,
        pillar=case.pillar.value,
        borrower=", ".join(case.borrower_names or []) or case.title,
    )
    runs = await newest_runs(session, case_id, features)
    run_ids = {str(r.id) for r in runs.values()}
    for feature, run in runs.items():
        calcs = (
            await session.execute(
                sa.select(Calculation)
                .where(Calculation.run_id == run.id)
                .order_by(Calculation.name, Calculation.created_at)
            )
        ).scalars()
        seen: set[str] = set()
        for c in calcs:
            if c.name in seen:
                continue
            seen.add(c.name)
            dossier.facts.append(
                Fact(
                    ref=f"{feature.value}.{c.name}",
                    label=c.formula,
                    value=shown(c.value, c.unit),
                    working=c.working,
                    evidence={"type": "calculation", "name": c.name, "id": str(c.id)},
                )
            )

    skip = set(skip_codes)
    flags = (
        await session.execute(
            sa.select(Flag)
            .where(Flag.case_id == case_id, Flag.status == FlagStatus.OPEN)
            .order_by(Flag.code, Flag.created_at, Flag.id)
        )
    ).scalars()
    grouped: dict[str, list[Flag]] = {}
    for flag in flags:
        if flag.code in skip:
            continue
        run_id = (flag.evidence or {}).get("run_id")
        if run_id is not None and str(run_id) not in run_ids:
            continue  # raised by an older run of its feature
        grouped.setdefault(flag.code, []).append(flag)
    for code, rows in grouped.items():
        messages = tuple(dict.fromkeys(r.message for r in rows))
        refs: list[dict[str, Any]] = []
        for r in rows:
            for ref in (r.evidence or {}).get("refs") or []:
                if isinstance(ref, dict) and ref.get("document_id"):
                    refs.append(
                        {
                            "type": "document",
                            "document_id": ref["document_id"],
                            "line_ids": list(ref.get("line_ids") or []),
                        }
                    )
        worst = (
            "error" if any(r.severity.value == "error" for r in rows) else rows[0].severity.value
        )
        dossier.flags.append(
            FlagGroup(code, worst, messages, tuple(r.id for r in rows), tuple(refs[:6]))
        )

    completeness = await latest_view(session, case_id)
    if completeness is not None:
        for item in completeness.items():
            if item.effective in ("satisfied", "overridden"):
                continue
            dossier.gaps.append(
                Fact(
                    ref=f"checklist.{item.item_id}",
                    label=item.label,
                    value=f"{item.status}: {item.reason}",
                    evidence={"type": "checklist", "id": item.item_id},
                )
            )
    return dossier

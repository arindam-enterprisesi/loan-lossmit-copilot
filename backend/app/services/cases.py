"""Cases: create, list, read and set the borrower profile, with visibility by role.

Which role sees which pillar comes from the Feature Design (Feature 1, "Users"):
the loan processor or underwriter works Pillar 1, the loss mitigation specialist
works Pillar 2, and the administrator sees both. A case the caller cannot see is
reported as not found, so its existence is not revealed.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date
from typing import Any

import sqlalchemy as sa
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.enums import EmploymentType, Pillar, Role
from app.db.models import Case, Document
from app.services import audit
from app.services.security import CurrentUser

ROLE_PILLARS: dict[Role, frozenset[Pillar]] = {
    Role.UNDERWRITER: frozenset({Pillar.UNDERWRITING}),
    Role.LM_SPECIALIST: frozenset({Pillar.LOSS_MITIGATION}),
    Role.ADMIN: frozenset({Pillar.UNDERWRITING, Pillar.LOSS_MITIGATION}),
}

# Human case references: LP-0001 (the underwriting pillar, "loan processing" in the schema doc)
# and LM-0001 (loss mitigation). Each prefix has its own Postgres sequence, created by migration
# 0001, so a number is never reused after a case is deleted.
CASE_REF_PREFIX: dict[Pillar, str] = {Pillar.UNDERWRITING: "LP", Pillar.LOSS_MITIGATION: "LM"}
CASE_REF_SEQUENCE: dict[Pillar, str] = {
    Pillar.UNDERWRITING: "case_ref_lp_seq",
    Pillar.LOSS_MITIGATION: "case_ref_lm_seq",
}


async def next_case_ref(session: AsyncSession, pillar: Pillar) -> str:
    number = await session.scalar(select(sa.Sequence(CASE_REF_SEQUENCE[pillar]).next_value()))
    return f"{CASE_REF_PREFIX[pillar]}-{number:04d}"


async def advance_case_ref_sequences(session: AsyncSession) -> None:
    """Make the next generated ref higher than every ref already stored. Never lowers a sequence.

    Needed after rows are inserted with explicit refs (the seed), which do not touch the sequence.
    """
    for pillar, prefix in CASE_REF_PREFIX.items():
        sequence = CASE_REF_SEQUENCE[pillar]  # a constant from this module, never user input
        await session.execute(
            sa.text(
                f"""
                SELECT setval('{sequence}', greatest(
                    (SELECT max(CAST(substr(case_ref, 4) AS integer)) FROM cases
                     WHERE case_ref LIKE :prefix),
                    (SELECT last_value FROM {sequence})
                ))
                WHERE EXISTS (SELECT 1 FROM cases WHERE case_ref LIKE :prefix)
                """
            ),
            {"prefix": f"{prefix}-%"},
        )


@dataclass(frozen=True)
class CaseView:
    case: Case
    document_count: int


def can_access(role: Role, pillar: Pillar) -> bool:
    return pillar in ROLE_PILLARS[role]


def _with_document_count() -> Any:
    count = (
        select(func.count(Document.id))
        .where(Document.case_id == Case.id)
        .correlate(Case)
        .scalar_subquery()
    )
    return select(Case, count.label("document_count"))


async def list_cases(
    session: AsyncSession, role: Role, pillar: Pillar | None = None
) -> list[CaseView]:
    visible = ROLE_PILLARS[role]
    if pillar is not None:
        # Filtering on a pillar the caller cannot see is an empty list, not an error.
        visible = visible & {pillar}
    rows = await session.execute(
        _with_document_count()
        .where(Case.pillar.in_(visible))
        .order_by(Case.created_at.desc(), Case.title)
    )
    return [CaseView(case, count) for case, count in rows.all()]


async def get_case(session: AsyncSession, role: Role, case_id: uuid.UUID) -> CaseView | None:
    """The case, or None when it does not exist or the role cannot see it."""
    row = (
        await session.execute(
            _with_document_count().where(Case.id == case_id, Case.pillar.in_(ROLE_PILLARS[role]))
        )
    ).one_or_none()
    return CaseView(row[0], row[1]) if row is not None else None


async def create_case(
    session: AsyncSession, user: CurrentUser, title: str, pillar: Pillar
) -> CaseView:
    case = Case(
        title=title,
        pillar=pillar,
        case_ref=await next_case_ref(session, pillar),
        created_by=uuid.UUID(user.id),
    )
    session.add(case)
    await session.flush()
    await session.refresh(case)
    await audit.record(
        session,
        actor_id=uuid.UUID(user.id),
        role=user.role.value,
        action="case.created",
        entity_type="case",
        entity_id=case.id,
        case_id=case.id,
        after={
            "case_ref": case.case_ref,
            "title": case.title,
            "pillar": case.pillar.value,
            "status": case.status,
        },
    )
    return CaseView(case, 0)


def _profile_snapshot(case: Case) -> dict[str, Any]:
    return {
        "borrower_names": case.borrower_names,
        "employment_type": case.employment_type.value if case.employment_type else None,
        "reference_date": case.reference_date.isoformat() if case.reference_date else None,
    }


async def set_profile(
    session: AsyncSession,
    user: CurrentUser,
    case_id: uuid.UUID,
    *,
    borrower_names: list[str],
    employment_type: EmploymentType,
    reference_date: date,
) -> CaseView | None:
    """Replace the profile. The previous values are kept in the audit event."""
    view = await get_case(session, user.role, case_id)
    if view is None:
        return None
    case = view.case
    before = _profile_snapshot(case)

    case.borrower_names = borrower_names
    case.employment_type = employment_type
    case.reference_date = reference_date
    await session.flush()

    await audit.record(
        session,
        actor_id=uuid.UUID(user.id),
        role=user.role.value,
        action="case.profile_updated",
        entity_type="case",
        entity_id=case.id,
        case_id=case.id,
        before=before,
        after=_profile_snapshot(case),
    )
    return view

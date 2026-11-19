"""Seed the demo users and cases (``make seed`` / ``python -m app.db.seed``).

Safe to run repeatedly: IDs are derived from fixed names and rows that already
exist are left alone. The two cases start empty (no documents); the borrower's
profile is entered later through ``PUT /cases/{id}/profile``.
"""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.enums import Pillar, Role
from app.db.models import Case, User
from app.db.session import get_engine, get_sessionmaker
from app.services.cases import advance_case_ref_sequences
from app.services.security import hash_password
from app.settings import get_settings

# Fixed namespace so every run (and every machine) derives the same IDs.
SEED_NAMESPACE = uuid.UUID("6f1c5d1e-3b0a-4c64-9a53-0d4f7b2f8e11")

# One demo user per role: (username, display name, role).
DEMO_USERS: tuple[tuple[str, str, Role], ...] = (
    ("underwriter", "Demo Underwriter", Role.UNDERWRITER),
    ("lm_specialist", "Demo Loss Mitigation Specialist", Role.LM_SPECIALIST),
    ("admin", "Demo Administrator", Role.ADMIN),
)

# (title, pillar, case_ref, username of the creating user)
DEMO_CASES: tuple[tuple[str, Pillar, str, str], ...] = (
    ("Daniel Reyes — purchase", Pillar.UNDERWRITING, "LP-0001", "underwriter"),
    ("Angela Whitfield — hardship", Pillar.LOSS_MITIGATION, "LM-0001", "lm_specialist"),
)


@dataclass(frozen=True)
class SeedResult:
    users_created: int
    cases_created: int


def user_id(username: str) -> uuid.UUID:
    return uuid.uuid5(SEED_NAMESPACE, f"user:{username}")


def case_id(title: str) -> uuid.UUID:
    return uuid.uuid5(SEED_NAMESPACE, f"case:{title}")


async def seed(session: AsyncSession, demo_password: str) -> SeedResult:
    """Insert the demo users and cases that are missing. The caller commits."""
    if not demo_password:
        raise ValueError("DEMO_PASSWORD must not be empty")

    users_created = cases_created = 0
    for username, name, role in DEMO_USERS:
        result = await session.execute(
            insert(User)
            .values(
                id=user_id(username),
                username=username,
                name=name,
                role=role,
                password_hash=hash_password(demo_password),
            )
            .on_conflict_do_nothing()
        )
        users_created += result.rowcount  # type: ignore[attr-defined]

    for title, pillar, case_ref, creator in DEMO_CASES:
        result = await session.execute(
            insert(Case)
            .values(
                id=case_id(title),
                case_ref=case_ref,
                title=title,
                pillar=pillar,
                created_by=user_id(creator),
            )
            .on_conflict_do_nothing()
        )
        cases_created += result.rowcount  # type: ignore[attr-defined]

    # The refs above were written explicitly, so the sequences must be moved past them or the
    # first case created through the API would try to take LP-0001 again.
    await advance_case_ref_sequences(session)

    return SeedResult(users_created, cases_created)


async def _main() -> None:
    password = get_settings().demo_password.get_secret_value()
    try:
        async with get_sessionmaker()() as session:
            result = await seed(session, password)
            await session.commit()
    finally:
        await get_engine().dispose()
    print(
        f"Seed done: {result.users_created} user(s) and {result.cases_created} case(s) created "
        f"({len(DEMO_USERS)} users and {len(DEMO_CASES)} cases in total)."
    )


def main() -> None:
    asyncio.run(_main())


if __name__ == "__main__":
    main()

"""The seed script: three demo users (one per role) and two empty cases."""

from __future__ import annotations

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.enums import Pillar, Role
from app.db.models import Case, Document, User
from app.db.seed import DEMO_CASES, DEMO_USERS, case_id, seed, user_id
from app.services.cases import next_case_ref
from app.services.security import verify_password

PASSWORD = "demo-pass"


async def test_creates_one_user_per_role(session: AsyncSession) -> None:
    result = await seed(session, PASSWORD)
    assert (result.users_created, result.cases_created) == (3, 2)

    users = (await session.execute(sa.select(User).order_by(User.username))).scalars().all()
    assert {u.username: u.role for u in users} == {
        "admin": Role.ADMIN,
        "lm_specialist": Role.LM_SPECIALIST,
        "underwriter": Role.UNDERWRITER,
    }
    assert sorted(u.role for u in users) == sorted(Role)
    for u in users:
        assert verify_password(PASSWORD, u.password_hash)
        assert PASSWORD not in u.password_hash


async def test_creates_two_empty_cases(session: AsyncSession) -> None:
    await seed(session, PASSWORD)

    cases = (await session.execute(sa.select(Case).order_by(Case.title))).scalars().all()
    assert [(c.title, c.pillar, c.case_ref) for c in cases] == [
        ("Angela Whitfield — hardship", Pillar.LOSS_MITIGATION, "LM-0001"),
        ("Daniel Reyes — purchase", Pillar.UNDERWRITING, "LP-0001"),
    ]
    for c in cases:
        # The profile is entered later; the seed only creates the case.
        assert (c.borrower_names, c.employment_type, c.reference_date) == (None, None, None)
        assert c.status == "open"
    created_by = {c.title: c.created_by for c in cases}
    assert created_by["Daniel Reyes — purchase"] == user_id("underwriter")
    assert created_by["Angela Whitfield — hardship"] == user_id("lm_specialist")

    documents = await session.scalar(sa.select(sa.func.count()).select_from(Document))
    assert documents == 0


async def test_running_it_twice_changes_nothing(session: AsyncSession) -> None:
    await seed(session, PASSWORD)
    before = (await session.execute(sa.select(User.id, User.password_hash))).all()

    again = await seed(session, PASSWORD)

    assert (again.users_created, again.cases_created) == (0, 0)
    assert await session.scalar(sa.select(sa.func.count()).select_from(User)) == len(DEMO_USERS)
    assert await session.scalar(sa.select(sa.func.count()).select_from(Case)) == len(DEMO_CASES)
    assert (await session.execute(sa.select(User.id, User.password_hash))).all() == before


async def test_refs_are_kept_when_it_runs_again(session: AsyncSession) -> None:
    await seed(session, PASSWORD)
    await seed(session, PASSWORD)

    refs = (await session.execute(sa.select(Case.title, Case.case_ref))).all()
    assert dict(refs) == {
        "Daniel Reyes — purchase": "LP-0001",
        "Angela Whitfield — hardship": "LM-0001",
    }


async def test_new_cases_continue_after_the_seeded_refs(session: AsyncSession) -> None:
    await seed(session, PASSWORD)

    # The seed wrote LP-0001 / LM-0001 explicitly, so it must move the sequences past them.
    first_lp = await next_case_ref(session, Pillar.UNDERWRITING)
    first_lm = await next_case_ref(session, Pillar.LOSS_MITIGATION)
    assert first_lp not in {"LP-0001"} and first_lp.startswith("LP-")
    assert first_lm not in {"LM-0001"} and first_lm.startswith("LM-")

    # Running it again never moves a sequence backwards.
    await seed(session, PASSWORD)
    second_lp = await next_case_ref(session, Pillar.UNDERWRITING)
    assert int(second_lp[3:]) > int(first_lp[3:])


def test_ids_are_stable_across_runs() -> None:
    assert user_id("admin") == user_id("admin")
    assert user_id("admin") != user_id("underwriter")
    assert case_id("Daniel Reyes — purchase") == case_id("Daniel Reyes — purchase")


async def test_empty_password_refused(session: AsyncSession) -> None:
    with pytest.raises(ValueError, match="DEMO_PASSWORD"):
        await seed(session, "")

"""The loan scenario service: entered once, replaced with the old values kept in the audit event."""

from __future__ import annotations

import uuid
from decimal import Decimal as D

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.enums import Role
from app.db.models import AuditEvent
from app.services.loan_scenarios import (
    ScenarioError,
    ScenarioValues,
    as_input,
    get_scenario,
    put_scenario,
)
from app.services.security import CurrentUser

DANIEL = ScenarioValues(
    purpose="Purchase",
    occupancy="Primary residence",
    property_value=D("300000"),
    loan_amount=D("270000"),
    proposed_housing_payment=D("1850"),
    funds_to_close=D("36500"),
)


def underwriter(user_id: uuid.UUID) -> CurrentUser:
    return CurrentUser(id=str(user_id), name="Test User", role=Role.UNDERWRITER)


async def events(session: AsyncSession, case_id: uuid.UUID) -> list[AuditEvent]:
    rows = await session.execute(
        sa.select(AuditEvent).where(AuditEvent.case_id == case_id).order_by(AuditEvent.id)
    )
    return list(rows.scalars())


async def test_a_new_scenario_is_stored_to_the_cent_and_audited(
    session: AsyncSession, case_id: uuid.UUID, user_id: uuid.UUID
) -> None:
    await put_scenario(session, underwriter(user_id), case_id, DANIEL)

    row = await get_scenario(session, case_id)

    assert row is not None
    assert (row.property_value, row.loan_amount) == (D("300000.00"), D("270000.00"))
    assert row.created_by == user_id and row.updated_by is None
    [event] = await events(session, case_id)
    assert (event.action, event.before) == ("loan_scenario.entered", None)
    assert event.after and event.after["funds_to_close"] == "36500.00"


async def test_saving_again_replaces_it_and_the_audit_event_keeps_the_old_values(
    session: AsyncSession, case_id: uuid.UUID, user_id: uuid.UUID
) -> None:
    user = underwriter(user_id)
    await put_scenario(session, user, case_id, DANIEL)

    changed = ScenarioValues(**{**vars(DANIEL), "loan_amount": D("240000")})
    await put_scenario(session, user, case_id, changed)

    row = await get_scenario(session, case_id)
    assert row is not None and row.loan_amount == D("240000.00")
    assert row.updated_by == user_id and row.updated_at is not None
    replaced = (await events(session, case_id))[-1]
    assert replaced.action == "loan_scenario.replaced"
    assert replaced.before and replaced.before["loan_amount"] == "270000.00"
    assert replaced.after and replaced.after["loan_amount"] == "240000.00"
    count = await session.scalar(sa.text("SELECT count(*) FROM loan_scenarios"))
    assert count == 1


async def test_a_case_with_no_scenario_has_none(session: AsyncSession, case_id: uuid.UUID) -> None:
    assert await get_scenario(session, case_id) is None


@pytest.mark.parametrize(
    "changes",
    [
        {"property_value": D("0")},
        {"loan_amount": D("-1")},
        {"proposed_housing_payment": D("-0.01")},
        {"funds_to_close": D("-5")},
        {"purpose": "  "},
        {"occupancy": ""},
    ],
)
async def test_an_unusable_scenario_is_refused_and_nothing_is_stored(
    session: AsyncSession, case_id: uuid.UUID, user_id: uuid.UUID, changes: dict[str, object]
) -> None:
    bad = ScenarioValues(**{**vars(DANIEL), **changes})

    with pytest.raises(ScenarioError):
        await put_scenario(session, underwriter(user_id), case_id, bad)

    assert await get_scenario(session, case_id) is None
    assert await events(session, case_id) == []


async def test_the_analysis_reads_the_stored_scenario(
    session: AsyncSession, case_id: uuid.UUID, user_id: uuid.UUID
) -> None:
    row = await put_scenario(session, underwriter(user_id), case_id, DANIEL)

    scenario = as_input(row)

    assert scenario.loan_amount / scenario.property_value == D("0.9")

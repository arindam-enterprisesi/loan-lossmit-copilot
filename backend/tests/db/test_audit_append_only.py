"""audit_events is append-only: the database refuses changes, and so does the ORM."""

from __future__ import annotations

import uuid

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession

from app.db.models import AppendOnlyError, AuditEvent
from tests.db.conftest import expect_db_error


async def _insert_event(conn: AsyncConnection, case_id: uuid.UUID | None = None) -> int:
    result = await conn.execute(
        sa.text(
            "INSERT INTO audit_events (actor, case_id, action, entity, before, after, reason) "
            "VALUES ('system', :c, 'field.corrected', 'field:net_pay', "
            '\'{"value": "2083.61"}\', \'{"value": "2033.61"}\', \'net pay arithmetic\') '
            "RETURNING id"
        ),
        {"c": case_id},
    )
    return result.scalar_one()


async def _reason(conn: AsyncConnection, event_id: int) -> str:
    result = await conn.execute(
        sa.text("SELECT reason FROM audit_events WHERE id = :i"), {"i": event_id}
    )
    return result.scalar_one()


async def test_events_can_be_appended(conn: AsyncConnection) -> None:
    first, second = await _insert_event(conn), await _insert_event(conn)
    assert second > first
    row = (
        await conn.execute(
            sa.text("SELECT at, actor, before, after FROM audit_events WHERE id = :i"),
            {"i": first},
        )
    ).one()
    assert row.at is not None
    assert row.actor == "system"
    assert row.before == {"value": "2083.61"}
    assert row.after == {"value": "2033.61"}


async def test_update_is_rejected_by_the_database(conn: AsyncConnection) -> None:
    event_id = await _insert_event(conn)
    error = await expect_db_error(
        conn, "UPDATE audit_events SET reason = 'rewritten' WHERE id = :i", i=event_id
    )
    assert "append-only" in str(error)
    assert await _reason(conn, event_id) == "net pay arithmetic"


async def test_delete_is_rejected_by_the_database(conn: AsyncConnection) -> None:
    event_id = await _insert_event(conn)
    error = await expect_db_error(conn, "DELETE FROM audit_events WHERE id = :i", i=event_id)
    assert "append-only" in str(error)
    assert await _reason(conn, event_id) == "net pay arithmetic"


async def test_truncate_is_rejected_by_the_database(conn: AsyncConnection) -> None:
    event_id = await _insert_event(conn)
    error = await expect_db_error(conn, "TRUNCATE audit_events")
    assert "append-only" in str(error)
    assert await _reason(conn, event_id) == "net pay arithmetic"


async def test_orm_refuses_to_update_an_event(session: AsyncSession) -> None:
    event = AuditEvent(actor="system", action="case.created", entity="case")
    session.add(event)
    await session.flush()

    event.reason = "rewritten"
    with pytest.raises(AppendOnlyError, match="cannot be updated"):
        await session.flush()


async def test_orm_refuses_to_delete_an_event(session: AsyncSession) -> None:
    event = AuditEvent(actor="system", action="case.created", entity="case")
    session.add(event)
    await session.flush()

    await session.delete(event)
    with pytest.raises(AppendOnlyError, match="cannot be deleted"):
        await session.flush()


async def test_audit_history_does_not_need_the_case_to_exist(conn: AsyncConnection) -> None:
    # No foreign key: events outlive the case they describe.
    event_id = await _insert_event(conn, case_id=uuid.uuid4())
    assert await _reason(conn, event_id) == "net pay arithmetic"

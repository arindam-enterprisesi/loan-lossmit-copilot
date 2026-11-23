"""Audit Store (CPS-11): the one place that writes audit events.

Events are append-only (a database trigger enforces it). Record an event in the
same transaction as the change it describes, so both commit or neither does.
"""

from __future__ import annotations

import uuid
from typing import Any

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import AuditEvent, User


async def record(
    session: AsyncSession,
    *,
    actor_id: uuid.UUID | None,
    role: str,
    action: str,
    entity_type: str,
    entity_id: uuid.UUID | None = None,
    case_id: uuid.UUID | None = None,
    before: dict[str, Any] | None = None,
    after: dict[str, Any] | None = None,
    reason: str | None = None,
) -> AuditEvent:
    """Add one event to the session.

    ``actor_id`` is the user who acted; ``None`` means the system or a worker, and then ``role``
    says which (``system`` or ``worker``). For a user, ``role`` is their role.
    """
    event = AuditEvent(
        actor_id=actor_id,
        role=role,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        case_id=case_id,
        before=before,
        after=after,
        reason=reason,
    )
    session.add(event)
    await session.flush()
    return event


async def list_events(
    session: AsyncSession,
    case_id: uuid.UUID,
    *,
    action: str | None = None,
    entity_type: str | None = None,
    limit: int = 50,
    before: int | None = None,
) -> list[tuple[AuditEvent, str | None]]:
    """A case's events, newest first, with the actor's name. ``before`` is the id of the last event
    already seen, so a client pages by passing the last id it got. Asks for one more than ``limit``
    so the caller can tell whether there is another page."""
    query = (
        sa.select(AuditEvent, User.name)
        .outerjoin(User, User.id == AuditEvent.actor_id)
        .where(AuditEvent.case_id == case_id)
        .order_by(AuditEvent.id.desc())
        .limit(limit + 1)
    )
    if action:
        query = query.where(AuditEvent.action == action)
    if entity_type:
        query = query.where(AuditEvent.entity_type == entity_type)
    if before is not None:
        query = query.where(AuditEvent.id < before)
    return [(event, name) for event, name in (await session.execute(query)).all()]

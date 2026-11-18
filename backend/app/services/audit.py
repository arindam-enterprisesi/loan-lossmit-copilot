"""Audit Store (CPS-11): the one place that writes audit events.

Events are append-only (a database trigger enforces it). Record an event in the
same transaction as the change it describes, so both commit or neither does.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import AuditEvent


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

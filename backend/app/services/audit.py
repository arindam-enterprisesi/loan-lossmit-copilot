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
    actor: str,
    action: str,
    entity: str,
    case_id: uuid.UUID | None = None,
    before: dict[str, Any] | None = None,
    after: dict[str, Any] | None = None,
    reason: str | None = None,
) -> AuditEvent:
    """Add one event to the session. ``actor`` is a user ID, or ``system`` / ``worker``."""
    event = AuditEvent(
        actor=actor,
        action=action,
        entity=entity,
        case_id=case_id,
        before=before,
        after=after,
        reason=reason,
    )
    session.add(event)
    await session.flush()
    return event

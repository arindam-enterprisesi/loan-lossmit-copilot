"""The audit trail of a case as the API sends it (Feature Design: Audit Store)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel

from app.db.models import AuditEvent


class AuditEventOut(BaseModel):
    id: int
    at: datetime
    actor_id: uuid.UUID | None
    actor_name: str | None
    role: str
    action: str
    entity_type: str
    entity_id: uuid.UUID | None
    before: dict[str, Any] | None
    after: dict[str, Any] | None
    reason: str | None


class AuditPage(BaseModel):
    """Newest first. Pass ``next_before`` as ``before`` to read the next page; null at the end."""

    items: list[AuditEventOut]
    next_before: int | None


def event_from_row(event: AuditEvent, actor_name: str | None) -> AuditEventOut:
    return AuditEventOut(
        id=event.id,
        at=event.at,
        actor_id=event.actor_id,
        actor_name=actor_name,
        role=event.role,
        action=event.action,
        entity_type=event.entity_type,
        entity_id=event.entity_id,
        before=event.before,
        after=event.after,
        reason=event.reason,
    )

"""Append-only audit log (CPS-11): every upload, AI call, calculation and review action.

Append-only is enforced twice. The migration adds a Postgres trigger that rejects
UPDATE, DELETE and TRUNCATE (the app connects as the table owner, so revoking
grants would not stop it). The listeners below make the same mistake fail in
Python, with a clearer message, before it reaches the database.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

import sqlalchemy as sa
from sqlalchemy import event
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.engine import Connection
from sqlalchemy.orm import Mapped, Mapper, mapped_column

from app.db.base import Base
from app.db.models._common import TIMESTAMPTZ


class AppendOnlyError(RuntimeError):
    """Raised when code tries to change or delete an audit event."""


class AuditEvent(Base):
    __tablename__ = "audit_events"
    __table_args__ = (sa.Index("ix_audit_events_case_id_at", "case_id", "at"),)

    id: Mapped[int] = mapped_column(sa.BigInteger, sa.Identity(), primary_key=True)
    at: Mapped[datetime] = mapped_column(TIMESTAMPTZ, server_default=sa.func.now())
    # The user who acted; NULL means the system or a worker. Deliberately no foreign key: a
    # SET NULL cascade would be an UPDATE (blocked), and history must outlive its users.
    actor_id: Mapped[uuid.UUID | None] = mapped_column(sa.Uuid, nullable=True)
    # The user's role, or "system" / "worker" when actor_id is NULL. Plain text, no CHECK.
    role: Mapped[str] = mapped_column(sa.Text)
    # Deliberately no foreign key: audit history must survive deleting a case,
    # and that deletion is itself logged.
    case_id: Mapped[uuid.UUID | None] = mapped_column(sa.Uuid, nullable=True)
    action: Mapped[str] = mapped_column(sa.Text)
    entity_type: Mapped[str] = mapped_column(sa.Text)
    entity_id: Mapped[uuid.UUID | None] = mapped_column(sa.Uuid, nullable=True)
    before: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    after: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    reason: Mapped[str | None] = mapped_column(sa.Text, nullable=True)


@event.listens_for(AuditEvent, "before_update")
def _block_update(mapper: Mapper[Any], connection: Connection, target: AuditEvent) -> None:
    raise AppendOnlyError("audit_events is append-only: events cannot be updated")


@event.listens_for(AuditEvent, "before_delete")
def _block_delete(mapper: Mapper[Any], connection: Connection, target: AuditEvent) -> None:
    raise AppendOnlyError("audit_events is append-only: events cannot be deleted")

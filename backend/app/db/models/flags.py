"""Flags: every warning from every feature, in one place (docs/database-schema.md, section 2).

A flag points at what it is about (``entity_type`` and ``entity_id``: a document or a field for
Feature 1, other entities for later features) and at its evidence. There is at most one flag per
entity and code, so a check can never flag the same thing twice; re-running a check updates or
closes that one row.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.enums import FlagSeverity, FlagStatus
from app.db.models._common import created_at_column, enum_type, uuid_pk


class Flag(Base):
    __tablename__ = "flags"
    __table_args__ = (
        sa.UniqueConstraint("entity_type", "entity_id", "code", name="uq_flags_entity_code"),
        sa.Index("ix_flags_case_id", "case_id"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    case_id: Mapped[uuid.UUID] = mapped_column(sa.ForeignKey("cases.id", ondelete="CASCADE"))
    # Which feature raised it ("documents" for Feature 1). Free text: later features add theirs.
    feature: Mapped[str] = mapped_column(sa.String(64))
    # "document" or "field" for Feature 1. Free text, and no foreign key: it is polymorphic.
    entity_type: Mapped[str] = mapped_column(sa.String(32))
    entity_id: Mapped[uuid.UUID] = mapped_column(sa.Uuid)
    # A stable rule or condition ID such as DI-CHK-02 (rule 2: every finding names its rule).
    code: Mapped[str] = mapped_column(sa.String(32))
    severity: Mapped[FlagSeverity] = mapped_column(enum_type(FlagSeverity, "severity"))
    message: Mapped[str] = mapped_column(sa.Text)
    # Where it came from on the page ({document_id, page, line_ids, bbox}) plus the working of
    # the calculation that raised it ({"working": {...}}).
    evidence: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    status: Mapped[FlagStatus] = mapped_column(
        enum_type(FlagStatus, "status"),
        default=FlagStatus.OPEN,
        server_default=FlagStatus.OPEN.value,
    )
    # NULL while open, or when the system closed it because its check now passes.
    resolved_by: Mapped[uuid.UUID | None] = mapped_column(sa.ForeignKey("users.id"), nullable=True)
    reason: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    created_at: Mapped[datetime] = created_at_column()

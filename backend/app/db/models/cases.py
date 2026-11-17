"""A case groups one borrower scenario's documents and results."""

from __future__ import annotations

import uuid
from datetime import date, datetime

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.enums import EmploymentType, Pillar
from app.db.models._common import created_at_column, enum_type, uuid_pk


class Case(Base):
    __tablename__ = "cases"

    id: Mapped[uuid.UUID] = uuid_pk()
    pillar: Mapped[Pillar] = mapped_column(enum_type(Pillar, "pillar"))
    title: Mapped[str] = mapped_column(sa.String(200))
    # The profile is entered later (PUT /cases/{id}/profile), so these start empty.
    borrower_names: Mapped[list[str] | None] = mapped_column(ARRAY(sa.Text), nullable=True)
    employment_type: Mapped[EmploymentType | None] = mapped_column(
        enum_type(EmploymentType, "employment_type"), nullable=True
    )
    reference_date: Mapped[date | None] = mapped_column(sa.Date, nullable=True)
    # Free-form: the Feature Design lists no case statuses, so none are invented here.
    status: Mapped[str] = mapped_column(sa.String(32), default="open", server_default="open")
    created_by: Mapped[uuid.UUID] = mapped_column(sa.ForeignKey("users.id"))
    created_at: Mapped[datetime] = created_at_column()

"""A case groups one borrower scenario's documents and results."""

from __future__ import annotations

import uuid
from datetime import date, datetime

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.enums import EmploymentType, Pillar
from app.db.models._common import created_at_column, enum_type, uuid_pk


class Case(Base):
    __tablename__ = "cases"
    __table_args__ = (
        # LP = the underwriting pillar (the schema doc calls it loan_processing); LM = loss
        # mitigation.
        sa.CheckConstraint("case_ref ~ '^(LP|LM)-[0-9]{4,}$'", name="case_ref_format"),
        sa.CheckConstraint(
            "borrower_names IS NULL OR jsonb_typeof(borrower_names) = 'array'",
            name="borrower_names_is_array",
        ),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    # Present now so Row-Level Security can be switched on in phase 2 without touching every
    # table. No foreign key and no index until then.
    tenant_id: Mapped[uuid.UUID | None] = mapped_column(sa.Uuid, nullable=True)
    # Human reference such as LP-0001. Assigned by app.services.cases from a sequence per prefix.
    case_ref: Mapped[str] = mapped_column(sa.String(32), unique=True)
    pillar: Mapped[Pillar] = mapped_column(enum_type(Pillar, "pillar"))
    title: Mapped[str] = mapped_column(sa.String(200))
    # The profile is entered later (PUT /cases/{id}/profile), so these start empty.
    # A JSON array of strings.
    borrower_names: Mapped[list[str] | None] = mapped_column(JSONB, nullable=True)
    employment_type: Mapped[EmploymentType | None] = mapped_column(
        enum_type(EmploymentType, "employment_type"), nullable=True
    )
    reference_date: Mapped[date | None] = mapped_column(sa.Date, nullable=True)
    # Free-form: the Feature Design lists no case statuses, so none are invented here.
    status: Mapped[str] = mapped_column(sa.String(32), default="open", server_default="open")
    created_by: Mapped[uuid.UUID] = mapped_column(sa.ForeignKey("users.id"))
    created_at: Mapped[datetime] = created_at_column()

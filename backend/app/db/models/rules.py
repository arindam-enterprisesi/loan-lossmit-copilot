"""The loss mitigation waterfall and the lender view (docs/database-schema.md, section 4).

Code applies the investor's rule set to a case in waterfall order and computes the lender's
comparison with foreclosure before any agent starts (Feature Design 8.4). A result here says what
the rules found; ``met`` means an option's conditions are met, and never that anything is offered or
approved (rule 3). An override keeps what the rules decided beside the reviewer's (rule 6).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.enums import WaterfallOption, WaterfallStatus
from app.db.models._common import TIMESTAMPTZ, created_at_column, enum_type, uuid_pk


class WaterfallResult(Base):
    __tablename__ = "waterfall_results"
    __table_args__ = (
        sa.UniqueConstraint("run_id", "option", name="uq_waterfall_results_run_id_option"),
        sa.CheckConstraint("order_no >= 1", name="order_no_positive"),
        # An override names its reason and who made it.
        sa.CheckConstraint(
            "NOT overridden OR (override_reason IS NOT NULL AND overridden_by IS NOT NULL)",
            name="override_has_reason_and_who",
        ),
        sa.Index("ix_waterfall_results_run_id", "run_id"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    run_id: Mapped[uuid.UUID] = mapped_column(sa.ForeignKey("analysis_runs.id", ondelete="CASCADE"))
    rule_set_version: Mapped[str] = mapped_column(sa.String(100))
    order_no: Mapped[int] = mapped_column(sa.Integer)
    option: Mapped[WaterfallOption] = mapped_column(enum_type(WaterfallOption, "option"))
    # The status after any overrides (what the screen shows); ``original_status`` is what the rules
    # alone found, kept when a person overrides a condition.
    status: Mapped[WaterfallStatus] = mapped_column(enum_type(WaterfallStatus, "status"))
    original_status: Mapped[WaterfallStatus] = mapped_column(
        enum_type(WaterfallStatus, "original_status")
    )
    # [{"id", "label", "expression", "values", "passage_id", "status", "override": {...}}]
    conditions: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, default=list, server_default=sa.text("'[]'::jsonb")
    )
    overridden: Mapped[bool] = mapped_column(sa.Boolean, default=False, server_default=sa.false())
    override_reason: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    overridden_by: Mapped[uuid.UUID | None] = mapped_column(
        sa.ForeignKey("users.id"), nullable=True
    )
    overridden_at: Mapped[datetime | None] = mapped_column(TIMESTAMPTZ, nullable=True)
    created_at: Mapped[datetime] = created_at_column()


class LenderView(Base):
    """The expected outcome of an option against foreclosure, with the settings it used."""

    __tablename__ = "lender_views"
    __table_args__ = (sa.UniqueConstraint("run_id", name="uq_lender_views_run_id"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    run_id: Mapped[uuid.UUID] = mapped_column(sa.ForeignKey("analysis_runs.id", ondelete="CASCADE"))
    foreclosure_loss: Mapped[Decimal] = mapped_column(sa.Numeric(14, 2))
    modification_cost: Mapped[Decimal] = mapped_column(sa.Numeric(14, 2))
    advantage: Mapped[Decimal] = mapped_column(sa.Numeric(14, 2))
    settings: Mapped[dict[str, Any]] = mapped_column(JSONB)
    # The stored calculations that hold each figure's working.
    calculation_ids: Mapped[list[uuid.UUID]] = mapped_column(ARRAY(sa.Uuid), default=list)
    created_at: Mapped[datetime] = created_at_column()

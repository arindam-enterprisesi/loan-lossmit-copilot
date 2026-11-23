"""The loan scenario of a Pillar 1 case: entered by hand, read back for the asset analysis.

A case has at most one scenario. Saving again replaces it, and the values it replaced go in the
audit event (who, when, before and after), so nothing is lost (rule 6). Nothing is priced here.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import LoanScenario
from app.services import audit
from app.services.assets import ScenarioInput
from app.services.security import CurrentUser

CENT = Decimal("0.01")
AMOUNT_FIELDS = ("property_value", "loan_amount", "proposed_housing_payment", "funds_to_close")


class ScenarioError(Exception):
    """A scenario the analysis cannot use. ``code`` and ``message`` are for the API."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code, self.message = code, message


@dataclass(frozen=True)
class ScenarioValues:
    purpose: str
    occupancy: str
    property_value: Decimal
    loan_amount: Decimal
    proposed_housing_payment: Decimal
    funds_to_close: Decimal


def _shown(row: LoanScenario | ScenarioValues) -> dict[str, Any]:
    return {
        "purpose": row.purpose,
        "occupancy": row.occupancy,
        **{name: str(getattr(row, name).quantize(CENT)) for name in AMOUNT_FIELDS},
    }


def _checked(values: ScenarioValues) -> ScenarioValues:
    if not values.purpose.strip() or not values.occupancy.strip():
        raise ScenarioError("invalid_scenario", "Purpose and occupancy are required.")
    if values.property_value <= 0:
        raise ScenarioError("invalid_scenario", "Property value must be more than zero.")
    for name in AMOUNT_FIELDS[1:]:
        if getattr(values, name) < 0:
            raise ScenarioError(
                "invalid_scenario", f"{name.replace('_', ' ').title()} is negative."
            )
    return ScenarioValues(
        values.purpose.strip(),
        values.occupancy.strip(),
        *(getattr(values, name).quantize(CENT) for name in AMOUNT_FIELDS),
    )


async def get_scenario(session: AsyncSession, case_id: uuid.UUID) -> LoanScenario | None:
    return await session.get(LoanScenario, case_id)


async def put_scenario(
    session: AsyncSession, user: CurrentUser, case_id: uuid.UUID, values: ScenarioValues
) -> LoanScenario:
    """Create the case's scenario, or replace it. Writes an audit event; the caller commits."""
    values = _checked(values)
    actor = uuid.UUID(user.id)
    now = datetime.now(UTC)
    row = await session.get(LoanScenario, case_id)
    before = _shown(row) if row else None
    if row is None:
        row = LoanScenario(case_id=case_id, created_by=actor, **vars(values))
        session.add(row)
    else:
        for name, value in vars(values).items():
            setattr(row, name, value)
        row.updated_by, row.updated_at = actor, now
    await session.flush()
    await audit.record(
        session,
        actor_id=actor,
        role=user.role.value,
        action="loan_scenario.replaced" if before else "loan_scenario.entered",
        entity_type="loan_scenario",
        entity_id=case_id,
        case_id=case_id,
        before=before,
        after=_shown(values),
    )
    return row


def as_input(row: LoanScenario) -> ScenarioInput:
    """The scenario as the analysis reads it."""
    return ScenarioInput(
        purpose=row.purpose,
        occupancy=row.occupancy,
        property_value=row.property_value,
        loan_amount=row.loan_amount,
        proposed_housing_payment=row.proposed_housing_payment,
        funds_to_close=row.funds_to_close,
    )

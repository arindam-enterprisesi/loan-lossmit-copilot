"""Seed a loss mitigation case's simulated servicing record (Feature Design 7.3 and 8.3).

The record is the demo's stand-in for the servicer's system: the balance, payment parts, arrears and
how many months the loan is delinquent. The rules read months delinquent from it (no document
carries it) and use it for the balance, payment and arrears when the mortgage statement was not
read. It is generated with the scenario (``loan_record`` in ``data/synthetic/scenarios``), labelled
``synthetic`` and never real.
"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal
from typing import Any

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.enums import LoanRecordSource
from app.db.models import LoanRecord


async def seed_loan_record(
    session: AsyncSession, case_id: uuid.UUID, record: dict[str, Any]
) -> LoanRecord:
    """Store the scenario's loan record for the case unless it has one. The caller commits."""
    existing = await session.scalar(sa.select(LoanRecord).where(LoanRecord.case_id == case_id))
    if existing is not None:
        return existing
    row = LoanRecord(
        case_id=case_id,
        loan_id=record["loan_id"],
        investor=record["investor"],
        unpaid_balance=Decimal(record["unpaid_principal_balance"]),
        monthly_payment=Decimal(record["monthly_payment"]),
        principal_interest=Decimal(record["principal_and_interest"]),
        escrow=Decimal(record["escrow"]),
        next_due_date=date.fromisoformat(record["next_due_date"]),
        months_delinquent=int(record["months_delinquent"]),
        arrears_amount=Decimal(record["past_due_amount"]),
        source=LoanRecordSource.SYNTHETIC,
    )
    session.add(row)
    await session.flush()
    return row

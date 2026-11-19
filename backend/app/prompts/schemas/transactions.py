"""Output model for label-transactions@1 (Feature Design 3.5).

The category list is fixed by the Feature Design, so it is a closed set here,
not configuration. The model labels; it never decides whether a deposit is
acceptable, adds amounts or compares figures.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class TransactionCategory(StrEnum):
    PAYROLL_DEPOSIT = "payroll deposit"
    OTHER_INCOME_DEPOSIT = "other income deposit"
    TRANSFER_IN = "transfer in"
    TRANSFER_OUT = "transfer out"
    HOUSING_PAYMENT = "housing payment"
    LOAN_PAYMENT = "loan payment"
    CREDIT_CARD_PAYMENT = "credit card payment"
    UTILITY = "utility"
    INSURANCE = "insurance"
    EVERYDAY_SPENDING = "everyday spending"
    OVERDRAFT_OR_RETURNED_ITEM_FEE = "overdraft or returned-item fee"
    OTHER_FEE = "other fee"
    REFUND = "refund"
    OTHER = "other"


class TransactionLabel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    line_id: str = Field(description='The transaction\'s line ID exactly as given, e.g. "p1-L14".')
    category: TransactionCategory
    counterparty: str | None = Field(
        description="A cleaned-up name of the other party, or null if it cannot be told."
    )


class LabelTransactionsResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    labels: list[TransactionLabel]

"""Closed value sets shared by the database models and the API.

Values are copied from ``contracts/openapi.yaml``. The database stores them as
VARCHAR with a CHECK constraint (not a Postgres enum type), so adding a value
later is an ordinary migration.
"""

from __future__ import annotations

from enum import StrEnum


class Role(StrEnum):
    UNDERWRITER = "underwriter"  # covers the loan processor or underwriter role
    LM_SPECIALIST = "lm_specialist"
    ADMIN = "admin"


class Pillar(StrEnum):
    UNDERWRITING = "underwriting"
    LOSS_MITIGATION = "loss_mitigation"


class EmploymentType(StrEnum):
    WAGE_EARNER = "wage_earner"
    SELF_EMPLOYED = "self_employed"
    RETIRED = "retired"
    OTHER = "other"


class Certainty(StrEnum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class DocumentStatus(StrEnum):
    UPLOADED = "uploaded"
    PROCESSING = "processing"
    TYPE_NEEDED = "type_needed"
    NEEDS_REVIEW = "needs_review"
    REVIEWED = "reviewed"
    FAILED = "failed"


class ReviewStatus(StrEnum):
    UNREVIEWED = "unreviewed"
    CONFIRMED = "confirmed"
    CORRECTED = "corrected"
    REJECTED = "rejected"


class JobStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


# The next two come from docs/database-schema.md; the contract does not mention them.
class DocTypeSource(StrEnum):
    """Who decided ``documents.doc_type``: the classifier or a person."""

    AI = "ai"
    USER = "user"


class ReadBy(StrEnum):
    """How a page's text was read."""

    TEXT_LAYER = "text_layer"
    TESSERACT = "tesseract"


class DocumentType(StrEnum):
    """The contract's document types.

    Not enforced by a database CHECK: document types are administrator-managed
    configuration (Schema Registry, CPS-03), so ``documents.doc_type`` is plain
    text and the API validates it against this list.
    """

    PAY_STUB = "pay_stub"
    BANK_STATEMENT = "bank_statement"
    TAX_RETURN_1040 = "tax_return_1040"
    W2 = "w2"
    CREDIT_REPORT = "credit_report"
    MORTGAGE_ASSISTANCE_APPLICATION = "mortgage_assistance_application"
    MORTGAGE_STATEMENT = "mortgage_statement"
    BENEFITS_LETTER = "benefits_letter"
    EXPENSE_BILL = "expense_bill"
    HARDSHIP_LETTER = "hardship_letter"
    UNRECOGNIZED = "unrecognized"

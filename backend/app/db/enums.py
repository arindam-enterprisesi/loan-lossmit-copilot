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


class FlagSeverity(StrEnum):
    """The contract's Severity values."""

    ERROR = "error"
    WARNING = "warning"
    INFO = "info"


class FlagStatus(StrEnum):
    """docs/database-schema.md: open until a person, or a re-run of its check, closes it."""

    OPEN = "open"
    RESOLVED = "resolved"
    OVERRIDDEN = "overridden"


class ConfigKind(StrEnum):
    """docs/database-schema.md, ``config_versions.kind``: which settings file a version is of."""

    CHECKLIST = "checklist"
    INCOME_METHOD = "income_method"
    THRESHOLDS = "thresholds"
    RULE_SET = "rule_set"
    LLM = "llm"
    TEMPLATES = "templates"


class ConfigLabel(StrEnum):
    """Every setting is labelled (CLAUDE.md rule 4)."""

    ILLUSTRATIVE = "illustrative"
    AUTHORITATIVE = "authoritative"


class AnalysisFeature(StrEnum):
    """``analysis_runs.feature``: what a run is of."""

    INCOME = "income"
    ASSETS = "assets"
    CREDIT = "credit"
    HARDSHIP = "hardship"
    UNDERWRITING = "underwriting"
    LM_RECOMMENDATION = "lm_recommendation"
    COMPLETENESS = "completeness"


class AnalysisStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class HardshipSource(StrEnum):
    """``hardship_profiles.source``: who or what produced the reading."""

    MODEL = "model"  # hardship@1 read the letter
    SEEDED_SAMPLE = "seeded_sample"  # the Feature Design 7.8 example, stored without a model call


class TransactionCategory(StrEnum):
    """``transactions.category``: the fixed list of Feature Design 3.5.

    Mirrors ``app.prompts.schemas.transactions.TransactionCategory`` (a test keeps them equal), so
    the database layer does not import the prompts package.
    """

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


class TransactionDirection(StrEnum):
    """Which way money moved. ``transactions.amount`` is always the size, never negative."""

    CREDIT = "credit"
    DEBIT = "debit"


class CategorySource(StrEnum):
    """Who decided ``transactions.category``: the labelling model or a person."""

    AI = "ai"
    USER = "user"


class ObligationSource(StrEnum):
    """Where a recurring debt was found (Feature Design 3.2)."""

    BANK = "bank"
    CREDIT_REPORT = "credit_report"
    BOTH = "both"


class LoanRecordSource(StrEnum):
    """``loan_records.source``. The servicing record is simulated, never real."""

    SYNTHETIC = "synthetic"


class ReportKind(StrEnum):
    """``reports.kind``: which pillar's report it is."""

    UNDERWRITING = "underwriting"
    LM_RECOMMENDATION = "lm_recommendation"


class ReportStatus(StrEnum):
    """A report is a draft until a person has reviewed it; a sign-off records that review.

    ``signed_off`` says a person reviewed the report. It is not a decision (rule 3).
    """

    DRAFT = "draft"
    IN_REVIEW = "in_review"
    SIGNED_OFF = "signed_off"


class ReportSource(StrEnum):
    """Who wrote a report: the agents, or the seeded sample the demo starts from."""

    AGENTS = "agents"
    SEEDED_SAMPLE = "seeded_sample"


class ReviewPriority(StrEnum):
    """Review order for findings and conditions. It describes what to look at first, never
    eligibility (Feature Design 6.5)."""

    SIGNIFICANT = "significant"
    ATTENTION = "attention"
    INFORMATION = "information"


class ConditionSource(StrEnum):
    AGENT = "agent"
    USER = "user"


class ConditionDecision(StrEnum):
    """What the reviewer did with a suggested condition. Recording it is not a loan decision."""

    PENDING = "pending"
    ACCEPTED = "accepted"
    EDITED = "edited"
    REJECTED = "rejected"


class AgentName(StrEnum):
    RESEARCHER = "researcher"
    WRITER = "writer"
    CRITIC = "critic"


class AgentRunStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class WaterfallOption(StrEnum):
    """The loss mitigation options in waterfall order (Feature Design 8.3)."""

    REPAYMENT_PLAN = "repayment_plan"
    FORBEARANCE = "forbearance"
    PAYMENT_DEFERRAL = "payment_deferral"
    LOAN_MODIFICATION = "loan_modification"
    SHORT_SALE = "short_sale"
    DEED_IN_LIEU = "deed_in_lieu"


class WaterfallStatus(StrEnum):
    """What the rules found for an option. ``met`` says its conditions are met, nothing more."""

    MET = "met"
    NOT_MET = "not_met"
    NOT_EVALUABLE = "not_evaluable"
    NOT_REACHED = "not_reached"
    NEEDS_CONFIRMATION = "needs_confirmation"


class IncomeComponentKind(StrEnum):
    """``income_components.component`` (Feature Design 2.3: earnings are grouped by type)."""

    BASE = "base"
    OVERTIME = "overtime"
    BONUS = "bonus"
    COMMISSION = "commission"


class CompletenessOverall(StrEnum):
    """FSD section 7. The contract's overall status has only complete and incomplete."""

    COMPLETE = "complete"
    INCOMPLETE = "incomplete"
    NEEDS_REVIEW = "needs_review"


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

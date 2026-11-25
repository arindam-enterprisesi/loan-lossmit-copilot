"""Importing this package registers every table on ``Base.metadata`` (Alembic needs that)."""

from app.db.models.analysis import (
    AnalysisRun,
    Calculation,
    CompletenessResult,
    ConfigVersion,
    IncomeComponent,
)
from app.db.models.audit import AppendOnlyError, AuditEvent
from app.db.models.cases import Case
from app.db.models.credit import CreditInquiry, CreditScore, Tradeline
from app.db.models.documents import Document, Line, Page
from app.db.models.features import (
    BudgetLine,
    LoanRecord,
    LoanScenario,
    Obligation,
    Transaction,
)
from app.db.models.fields import ExtractionRun, Field
from app.db.models.flags import Flag
from app.db.models.hardship import HardshipProfile
from app.db.models.jobs import Job
from app.db.models.reports import AgentRun, Condition, Finding, Report, SignOff
from app.db.models.rules import LenderView, WaterfallResult
from app.db.models.users import User

__all__ = [
    "AgentRun",
    "AnalysisRun",
    "AppendOnlyError",
    "AuditEvent",
    "BudgetLine",
    "Calculation",
    "Case",
    "CompletenessResult",
    "Condition",
    "ConfigVersion",
    "CreditInquiry",
    "CreditScore",
    "Document",
    "ExtractionRun",
    "Field",
    "Finding",
    "Flag",
    "HardshipProfile",
    "IncomeComponent",
    "Job",
    "LenderView",
    "Line",
    "LoanRecord",
    "LoanScenario",
    "Obligation",
    "Page",
    "Report",
    "SignOff",
    "Tradeline",
    "Transaction",
    "User",
    "WaterfallResult",
]

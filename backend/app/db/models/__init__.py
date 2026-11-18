"""Importing this package registers every table on ``Base.metadata`` (Alembic needs that)."""

from app.db.models.audit import AppendOnlyError, AuditEvent
from app.db.models.cases import Case
from app.db.models.documents import Document, Line, Page
from app.db.models.fields import ExtractionRun, Field
from app.db.models.jobs import Job
from app.db.models.users import User

__all__ = [
    "AppendOnlyError",
    "AuditEvent",
    "Case",
    "Document",
    "ExtractionRun",
    "Field",
    "Job",
    "Line",
    "Page",
    "User",
]

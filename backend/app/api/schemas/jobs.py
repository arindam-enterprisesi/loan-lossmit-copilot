"""Background job shape, as in contracts/openapi.yaml (``Job``)."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.db.enums import JobStatus


class JobOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    kind: str
    status: JobStatus
    progress: float
    stage: str | None = None
    error: str | None = None
    created_at: datetime
    updated_at: datetime

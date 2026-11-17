"""Case request and response shapes, as in contracts/openapi.yaml."""

from __future__ import annotations

import uuid
from datetime import date, datetime

from pydantic import BaseModel, Field, field_validator

from app.db.enums import EmploymentType, Pillar
from app.services.cases import CaseView


class CaseCreate(BaseModel):
    title: str = Field(max_length=200)
    pillar: Pillar

    @field_validator("title")
    @classmethod
    def _title_not_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("title must not be blank")
        return value


class CaseProfile(BaseModel):
    borrower_names: list[str] = Field(min_length=1)
    employment_type: EmploymentType
    reference_date: date

    @field_validator("borrower_names")
    @classmethod
    def _names_not_blank(cls, names: list[str]) -> list[str]:
        cleaned = [name.strip() for name in names]
        if any(not name or len(name) > 200 for name in cleaned):
            raise ValueError("each borrower name must be 1 to 200 characters")
        return cleaned


class CaseOut(BaseModel):
    id: uuid.UUID
    title: str
    pillar: Pillar
    profile: CaseProfile | None
    document_count: int
    created_at: datetime

    @classmethod
    def from_view(cls, view: CaseView) -> CaseOut:
        case = view.case
        # The profile exists only once all three parts have been entered.
        profile = (
            CaseProfile(
                borrower_names=case.borrower_names,
                employment_type=case.employment_type,
                reference_date=case.reference_date,
            )
            if case.borrower_names and case.employment_type and case.reference_date
            else None
        )
        return cls(
            id=case.id,
            title=case.title,
            pillar=case.pillar,
            profile=profile,
            document_count=view.document_count,
            created_at=case.created_at,
        )


class CaseList(BaseModel):
    items: list[CaseOut]

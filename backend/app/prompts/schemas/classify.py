"""Output model for classify@1 (Feature Design 1.5, Classify call)."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from app.prompts.schemas.registry import DocumentType


class ClassifyResult(BaseModel):
    doc_type: DocumentType = Field(
        description='One registered document type, or "unrecognized" if none fits.'
    )
    certainty: Literal["high", "medium", "low"]
    justification_line_ids: list[str] = Field(
        description='IDs of the lines that show the type, e.g. "p1-L3".'
    )

"""Guideline sources and passages: read only (Feature 5 read side).

Any logged-in user may read them; they belong to no case. The screen opens a passage from the ID a
finding or a waterfall condition cites. The index itself (search, loading) is Arindam's, and there
are no ``POST`` routes here.

The contract has no entries for these yet; ``docs/contract-proposal-d4.md`` has the YAML.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.api.deps import get_current_user, require_roles
from app.api.errors import ApiError
from app.db.enums import Role
from app.services.guidelines import SEEDED_NOTICE, PassageStore, get_passage_store

router = APIRouter(
    prefix="/guidelines",
    tags=["guidelines"],
    dependencies=[
        Depends(get_current_user),
        Depends(require_roles(Role.UNDERWRITER, Role.LM_SPECIALIST, Role.ADMIN)),
    ],
)

Store = Annotated[PassageStore, Depends(get_passage_store)]


class SourceOut(BaseModel):
    id: str
    title: str
    kind: str
    label: str
    passage_count: int


class SourceList(BaseModel):
    items: list[SourceOut]


class PassageOut(BaseModel):
    id: str
    source_id: str
    source_title: str
    heading: str
    text: str
    label: str
    notice: str


@router.get("/sources", response_model=SourceList, operation_id="listGuidelineSources")
async def list_sources(store: Store) -> SourceList:
    return SourceList(items=[SourceOut(**vars(s)) for s in store.sources()])


@router.get("/passages/{passage_id}", response_model=PassageOut, operation_id="getGuidelinePassage")
async def get_passage(passage_id: str, store: Store) -> PassageOut:
    """One passage, by the ID a finding or condition cites."""
    found = store.passage(passage_id)
    if found is None:
        raise ApiError(404, "not_found", "Passage not found")
    return PassageOut(**vars(found), notice=SEEDED_NOTICE)

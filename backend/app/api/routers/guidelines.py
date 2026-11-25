"""Guideline sources, passages and the guideline assistant (Feature Design 5.7).

Any logged-in user may read and ask; sources belong to no case. The screen opens a passage from
the ID an answer, a finding or a waterfall condition cites. ``POST /ask`` answers from retrieved
passages only, with every sentence checked in code (``app.rag.answer``); with a case attached, the
case must be one the user may see. Every question, its retrieved passages, the answer and the
removed sentences go to the audit log, and so does feedback on an answer (Feature Design 5.6).
"""

from __future__ import annotations

import uuid
from typing import Annotated, Any, Literal

import sqlalchemy as sa
from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import case_not_found, get_current_user, require_roles
from app.api.errors import ApiError
from app.db.enums import Role
from app.db.models import AuditEvent
from app.db.session import get_session
from app.services import audit
from app.services.guidelines import SEEDED_NOTICE, PassageStore, get_passage_store
from app.services.security import CurrentUser

router = APIRouter(
    prefix="/guidelines",
    tags=["guidelines"],
    dependencies=[
        Depends(get_current_user),
        Depends(require_roles(Role.UNDERWRITER, Role.LM_SPECIALIST, Role.ADMIN)),
    ],
)

Store = Annotated[PassageStore, Depends(get_passage_store)]
User = Annotated[CurrentUser, Depends(get_current_user)]
Session = Annotated[AsyncSession, Depends(get_session)]


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
    notice = getattr(store, "notice", None)
    text = notice(passage_id) if notice else None
    return PassageOut(**vars(found), notice=text or SEEDED_NOTICE)


# --- the assistant ---------------------------------------------------------------------------


class AskIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question: str = Field(min_length=3, max_length=1000)
    source_set: Literal["guidelines", "regulation_x", "all"] = "all"
    case_id: uuid.UUID | None = None


class AnswerSentenceOut(BaseModel):
    text: str
    citations: list[int]


class AnswerCitationOut(BaseModel):
    marker: int
    passage_id: str


class AnswerPassageOut(BaseModel):
    id: str
    source_id: str
    source_title: str
    heading: str
    text: str
    label: str
    page: int | None
    version: str | None
    notice: str | None


class ComparisonOut(BaseModel):
    topic: str
    markers: list[int]


class GuidelineAnswerOut(BaseModel):
    id: uuid.UUID
    question: str
    source_set: str
    case_id: uuid.UUID | None
    asked_at: str
    status: Literal["answered", "no_support"]
    sentences: list[AnswerSentenceOut]
    citations: list[AnswerCitationOut]
    passages: list[AnswerPassageOut]
    comparison: ComparisonOut | None
    facts_to_check: list[str]
    notice: str | None
    removed_sentences: int


class FeedbackIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rating: Literal["helpful", "not_helpful", "wrongly_cited"]
    note: str | None = Field(default=None, max_length=1000)


@router.post("/ask", response_model=GuidelineAnswerOut, operation_id="askGuideline")
async def ask_guideline(body: AskIn, user: User, session: Session) -> GuidelineAnswerOut:
    """A cited answer from the loaded sources, or "no supporting passage found"."""
    from app.llm.gateway import GatewayError
    from app.rag.answer import ask
    from app.rag.case_facts import CaseNotVisibleError, facts_for_case

    facts: list[str] = []
    if body.case_id is not None:
        try:
            facts = await facts_for_case(session, user.role, body.case_id)
        except CaseNotVisibleError:
            raise case_not_found() from None
    try:
        answer = await ask(
            body.question.strip(),
            body.source_set,
            case_id=str(body.case_id) if body.case_id else None,
            case_facts=facts,
        )
    except GatewayError:
        raise ApiError(
            503, "model_unavailable", "The guideline assistant could not reach its model"
        ) from None
    await audit.record(
        session,
        actor_id=uuid.UUID(user.id),
        role=user.role.value,
        action="guideline.asked",
        entity_type="guideline_answer",
        entity_id=uuid.UUID(answer.id),
        case_id=body.case_id,
        after={
            "question": answer.question,
            "source_set": answer.source_set,
            "status": answer.status,
            "retrieved": answer.retrieved,
            "citations": answer.citations,
            "removed": answer.removed,
            "model": answer.model,
        },
    )
    await session.commit()
    return GuidelineAnswerOut.model_validate(answer.public())


@router.post("/answers/{answer_id}/feedback", status_code=204, operation_id="sendGuidelineFeedback")
async def send_feedback(answer_id: str, body: FeedbackIn, user: User, session: Session) -> None:
    """Helpful, not helpful or wrongly cited, with an optional note. Recorded in the audit log."""
    try:
        wanted = uuid.UUID(answer_id)
    except ValueError:
        raise ApiError(404, "not_found", "Answer not found") from None
    asked: Any = await session.scalar(
        sa.select(AuditEvent).where(
            AuditEvent.action == "guideline.asked", AuditEvent.entity_id == wanted
        )
    )
    if asked is None:
        raise ApiError(404, "not_found", "Answer not found")
    await audit.record(
        session,
        actor_id=uuid.UUID(user.id),
        role=user.role.value,
        action="guideline.feedback",
        entity_type="guideline_answer",
        entity_id=wanted,
        case_id=asked.case_id,
        after={"rating": body.rating, "note": body.note},
    )
    await session.commit()

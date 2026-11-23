"""The audit trail of a case: every upload, analysis, review action and sign-off, newest first.

Any logged-in role may read the trail of a case it can see (otherwise 404). Events are append-only
(a database trigger enforces it) and there is no endpoint that writes one.

The contract has no entry for this yet; ``docs/contract-proposal-d4.md`` has the YAML.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CaseIdPath, case_not_found, get_current_user, require_roles
from app.api.schemas.audit import AuditPage, event_from_row
from app.db.enums import Role
from app.db.session import get_session
from app.services import audit
from app.services import cases as case_service
from app.services.security import CurrentUser

router = APIRouter(
    prefix="/cases/{case_id}/audit",
    tags=["audit"],
    dependencies=[Depends(require_roles(Role.UNDERWRITER, Role.LM_SPECIALIST, Role.ADMIN))],
)

User = Annotated[CurrentUser, Depends(get_current_user)]
Session = Annotated[AsyncSession, Depends(get_session)]


@router.get("", response_model=AuditPage, operation_id="listCaseAudit")
async def list_case_audit(
    case_id: CaseIdPath,
    user: User,
    session: Session,
    action: Annotated[str | None, Query(max_length=100, description="Exact action name")] = None,
    entity_type: Annotated[str | None, Query(max_length=64)] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    before: Annotated[
        int | None, Query(ge=1, description="Id of the last event already seen")
    ] = None,
) -> AuditPage:
    """A case's events, newest first. Filter by action or entity_type; page by before."""
    if await case_service.get_case(session, user.role, case_id) is None:
        raise case_not_found()
    rows = await audit.list_events(
        session, case_id, action=action, entity_type=entity_type, limit=limit, before=before
    )
    page = rows[:limit]
    return AuditPage(
        items=[event_from_row(event, name) for event, name in page],
        next_before=page[-1][0].id if len(rows) > limit else None,
    )

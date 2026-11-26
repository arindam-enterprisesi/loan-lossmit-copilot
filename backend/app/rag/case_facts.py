"""A case's facts for case-aware questions (Feature Design 5.3: "Attach case").

Short neutral statements built in code from what is stored: the case reference and pillar, the
documents received with their dates, and the checklist items that are not satisfied. They go to
the model as data, so it can list the facts a person should check against each provision. No
conclusion about the borrower is drawn here.
"""

from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.enums import Role
from app.services import cases as case_service
from app.services.case_facts import load_case_documents
from app.services.completeness_runs import latest_view


class CaseNotVisibleError(LookupError):
    pass


async def facts_for_case(session: AsyncSession, role: Role, case_id: uuid.UUID) -> list[str]:
    view = await case_service.get_case(session, role, case_id)
    if view is None:
        raise CaseNotVisibleError(str(case_id))
    case = view.case
    facts = [f"Case {case.case_ref} ({case.pillar.value})"]
    if case.reference_date:
        facts.append(f"Case reference date: {case.reference_date.isoformat()}")
    for doc in await load_case_documents(session, case_id):
        kind = (doc.doc_type or "unclassified").replace("_", " ")
        facts.append(f"Received: {kind} ({doc.file_name}) on {doc.created_at.date().isoformat()}")
    completeness = await latest_view(session, case_id)
    if completeness is not None:
        for item in completeness.items():
            if item.effective not in ("satisfied", "overridden"):
                facts.append(f"Checklist: {item.label}: {item.status} ({item.reason})")
    return facts

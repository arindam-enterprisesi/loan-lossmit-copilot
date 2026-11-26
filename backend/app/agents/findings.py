"""The findings list, built in code from the dossier (Feature Design 6.5: "step 2 is code").

One finding per flag code (several payroll deposits that do not match a stub are one finding)
and one per checklist item that is not satisfied. Titles and details are the flags' own messages,
written by code; the agents never change a finding. Each finding carries its evidence: the rule
(flag code), the flags themselves and the document lines they point at, or the checklist item.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.agents.config import AgentsConfig
from app.agents.dossier import Dossier
from app.db.enums import ReviewPriority
from app.services.report_writer import FindingDraft

_ORDER = {ReviewPriority.SIGNIFICANT: 0, ReviewPriority.ATTENTION: 1, ReviewPriority.INFORMATION: 2}


@dataclass(frozen=True)
class CodedFinding:
    id: str  # "F1", "F2", ... in review order: what the Writer cites
    code: str  # the flag code, or "CHECKLIST"
    draft: FindingDraft
    topic: str  # the flag code, or "checklist.<item id>": picks the Researcher's question


def build_findings(dossier: Dossier, config: AgentsConfig) -> list[CodedFinding]:
    items: list[tuple[ReviewPriority, str, FindingDraft, str]] = []
    for group in dossier.flags:
        priority = config.priority(group.code)
        first = group.messages[0]
        title = first if len(group.messages) == 1 else f"{first} ({len(group.messages)} similar)"
        evidence: list[dict[str, Any]] = [{"type": "rule", "id": group.code}]
        evidence += [{"type": "flag", "id": str(i)} for i in group.flag_ids]
        evidence += list(group.refs)
        items.append(
            (
                priority,
                group.code,
                FindingDraft(
                    priority=priority,
                    title=title,
                    detail=" ".join(group.messages),
                    evidence=evidence,
                    flag_id=group.flag_ids[0],
                ),
                group.code,
            )
        )
    for gap in dossier.gaps:
        priority = config.priority("CHECKLIST")
        items.append(
            (
                priority,
                "CHECKLIST",
                FindingDraft(
                    priority=priority,
                    title=f"{gap.label}: not yet satisfied",
                    detail=gap.value,
                    evidence=[gap.evidence],
                ),
                gap.ref,
            )
        )
    items.sort(key=lambda x: _ORDER[x[0]])
    return [
        CodedFinding(f"F{n}", code, draft, topic)
        for n, (_, code, draft, topic) in enumerate(items, start=1)
    ]


def render_findings(findings: list[CodedFinding]) -> str:
    return "\n".join(
        f"- {f.id} | {f.draft.priority.value} | {f.code} | {f.draft.title}" for f in findings
    )

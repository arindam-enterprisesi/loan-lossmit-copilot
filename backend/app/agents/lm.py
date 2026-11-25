"""The loss mitigation recommendation's agents (Feature Design 8.5), after the rules ran in code.

    report = await run_lm_agents(session, run)                         # on a waterfall run
    report = await run_lm_agents(session, run, rerun=AgentName.WRITER)  # one agent again

The rules (``services.recommendation_runs``) decide every condition's status and compute the lender
view; the agents only explain them. The Researcher takes each reached option's rule passage from
the waterfall and asks the guideline assistant which Regulation X provisions may apply to the
case's facts. The report is written on the waterfall's own run, so ``GET .../latest`` shows the
waterfall and its report together.
"""

from __future__ import annotations

import json
from typing import Any

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.config import AgentsConfig, get_agents_config
from app.agents.dossier import LM_FEATURES, Dossier, build_dossier
from app.agents.findings import build_findings
from app.agents.workflow import (
    NOT_AVAILABLE,
    DraftSpec,
    Question,
    WorkflowState,
    _logged,
    render_guidance,
    research,
    write_and_check,
)
from app.db.enums import AgentName, AgentRunStatus, ReportKind, Role
from app.db.models import AgentRun, AnalysisRun, Report
from app.llm.gateway import Gateway
from app.llm.tasks import clean_text
from app.prompts.schemas.reports import LmDraft
from app.rag.case_facts import facts_for_case
from app.rag.store import RagStore, get_rag_store
from app.services import hardship_runs, report_writer
from app.services.report_writer import ReportDraft
from app.services.reports import load_waterfall_view

NOTE = (
    "Draft written by the agents from the rules' results. The rules mark which options have "
    "their conditions met; nothing here is a decision. Final terms are to be calculated under "
    "the investor's own method."
)
REGULATION_QUESTIONS = (
    "The application is missing a document. What must the servicer do?",
    "How long does a servicer have to evaluate a complete application?",
)


def render_waterfall(options: list[Any]) -> tuple[str, list[str]]:
    rows: list[str] = []
    passages: list[str] = []
    for o in options:
        rows.append(f"- option {o.order_no}: {o.option.value} | status {o.status.value}")
        for c in o.conditions:
            values = ", ".join(f"{k} {v}" for k, v in (c.get("values") or {}).items())
            rows.append(
                f"  - {c.get('label')} | {c.get('status')} | values: {values or '-'} | "
                f"passage {c.get('passage_id')}"
            )
            if o.status.value != "not_reached" and c.get("passage_id"):
                passages.append(str(c["passage_id"]))
    return "\n".join(clean_text(r) for r in rows), list(dict.fromkeys(passages))


def render_hardship(profile: Any) -> str:
    if profile is None:
        return "(no hardship profile)"
    parts = {
        "primary reason": profile.primary_reason,
        "onset": profile.onset,
        "duration": profile.duration,
        "intent": profile.intent,
    }
    rows = [clean_text(f"- {k}: {json.dumps(v, ensure_ascii=False)}") for k, v in parts.items()]
    rows.append(f"- confirmed by a person: {'yes' if profile.confirmed_at else 'no'}")
    return "\n".join(rows)


def rule_references(store: RagStore, passage_ids: list[str]) -> list[dict[str, Any]]:
    out = []
    for pid in passage_ids:
        passage = store.passage(pid)
        if passage is not None:
            out.append(
                {
                    "passage_id": pid,
                    "summary": f"{passage.heading}: {passage.text}",
                    "for": ["waterfall"],
                    "label": passage.label,
                    "source": f"{passage.source_title}, {passage.heading}",
                }
            )
    return out


async def run_lm_agents(
    session: AsyncSession,
    run: AnalysisRun,
    *,
    rerun: AgentName | None = None,
    config: AgentsConfig | None = None,
    gateway: Gateway | None = None,
    store: RagStore | None = None,
) -> Report:
    """Write the next report version on this waterfall run. Flushes; the caller commits."""
    config = config or get_agents_config()
    store = store or get_rag_store()
    previous: dict[str, dict[str, Any]] = {}
    if rerun is not None:
        rows = (
            await session.execute(
                sa.select(AgentRun)
                .where(AgentRun.run_id == run.id, AgentRun.status == AgentRunStatus.SUCCEEDED)
                .order_by(AgentRun.attempt)
            )
        ).scalars()
        previous = {row.agent.value: row.output or {} for row in rows}

    dossier: Dossier = await build_dossier(
        session, run.case_id, LM_FEATURES, skip_codes=config.skip_codes
    )
    findings = build_findings(dossier, config)
    view = await load_waterfall_view(session, run)
    waterfall_text, rule_passages = render_waterfall(view.options)
    hardship = await hardship_runs.latest(session, run.case_id)
    hardship_text = render_hardship(hardship.profile if hardship else None)
    case_facts = await facts_for_case(session, Role.LM_SPECIALIST, run.case_id)
    state = WorkflowState()

    async def researcher() -> tuple[dict[str, Any], dict[str, Any]]:
        found, info = await research(
            [Question("regulation_x", q, "regulation_x") for q in REGULATION_QUESTIONS],
            case_facts=case_facts,
            store=store,
            gateway=gateway,
            concurrency=config.researcher_concurrency,
        )
        found["references"] = rule_references(store, rule_passages) + found["references"]
        return found, info

    if rerun in (None, AgentName.RESEARCHER) or "researcher" not in previous:
        state.research = await _logged(session, run, AgentName.RESEARCHER, researcher, state)
    else:
        state.research = previous["researcher"]

    guidance = render_guidance(state.research)
    dossier_text = dossier.render()
    case = f"{dossier.case_ref}: {dossier.borrower}"

    def variables(fixes: str) -> dict[str, Any]:
        return {
            "case": case,
            "dossier": dossier_text,
            "waterfall": waterfall_text,
            "hardship": hardship_text,
            "guidance": guidance,
            "fixes": fixes,
        }

    spec = DraftSpec(
        task="lm_writer",
        prompt_id="lm-writer@1",
        output_model=LmDraft,
        variables=variables,
        evidence=(
            f"{dossier_text}\n\nWaterfall:\n{waterfall_text}\n\nHardship:\n{hardship_text}"
            f"\n\nGuidance:\n{guidance}"
        ),
        allowed=dossier.allowed_numbers(waterfall_text, guidance, hardship_text, *case_facts),
    )
    await write_and_check(
        session,
        run,
        spec,
        state,
        config,
        gateway=gateway,
        run_writer=rerun != AgentName.CRITIC or "writer" not in previous,
        previous_draft=previous.get("writer"),
    )
    draft = state.draft
    if draft is None:
        sections: dict[str, Any] = {
            "lender_view": NOT_AVAILABLE,
            "borrower_situation": NOT_AVAILABLE,
            "missing_information": [NOT_AVAILABLE],
            "compliance_points": [NOT_AVAILABLE],
            "items_for_human_review": [NOT_AVAILABLE],
        }
    else:
        sections = dict(draft)
    sections["guideline_references"] = [
        {"passage_id": r["passage_id"], "summary": r["summary"]}
        for r in (state.research or {}).get("references", [])
    ]
    sections["facts_to_check"] = (state.research or {}).get("facts_to_check", [])
    sections["note"] = NOTE
    report = await report_writer.write_report(
        session,
        run,
        ReportKind.LM_RECOMMENDATION,
        ReportDraft(
            sections=sections,
            findings=[f.draft for f in findings],
            conditions=[],
            guardrail_results={**state.guardrails, "agents_failed": state.failed},
        ),
    )
    return report

"""The underwriting copilot (Feature Design 6): findings in code, then Researcher, Writer, Critic.

    report = await run_underwriting(session, case_id)                       # a new run
    report = await run_underwriting(session, case_id, rerun=AgentName.CRITIC)  # one agent again

The report is written through ``report_writer`` as a draft; the underwriter reviews it. The
snapshot and the findings come from stored results; the agents write the narrative only.
"""

from __future__ import annotations

import uuid
from typing import Any

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.config import AgentsConfig, get_agents_config
from app.agents.dossier import UNDERWRITING_FEATURES, Dossier, build_dossier
from app.agents.findings import CodedFinding, build_findings, render_findings
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
from app.db.enums import (
    AgentName,
    AgentRunStatus,
    AnalysisFeature,
    AnalysisStatus,
    ReportKind,
    ReviewPriority,
)
from app.db.models import AgentRun, AnalysisRun, Report
from app.llm.gateway import Gateway
from app.prompts.schemas.reports import UnderwritingDraft
from app.rag.store import RagStore
from app.services import report_writer
from app.services.report_writer import ConditionDraft, ReportDraft

# What the snapshot shows, from stored results (ref -> label). Missing ones are left out.
SNAPSHOT = (
    ("income.candidate_monthly_income", "candidate_monthly_income"),
    ("assets.documented_assets", "documented_assets"),
    ("assets.funds_to_close", "funds_to_close"),
    ("assets.funds_shortfall", "funds_shortfall"),
    ("assets.monthly_obligations", "monthly_obligations"),
    ("assets.front_end_ratio", "front_end_ratio"),
    ("assets.dti", "dti"),
    ("assets.dti_with_overtime", "dti_with_overtime"),
    ("assets.ltv", "ltv"),
    ("credit.representative_score", "representative_score"),
)
NOTE = (
    "Draft written by the agents from stored results. Every figure comes from a stored "
    "calculation; nothing here is a decision."
)


def snapshot(dossier: Dossier) -> dict[str, str]:
    out = {"borrower": dossier.borrower, "case": dossier.case_ref}
    for ref, label in SNAPSHOT:
        fact = dossier.fact(ref)
        if fact is not None:
            out[label] = fact.value
    return out


def questions(findings: list[CodedFinding], config: AgentsConfig) -> list[Question]:
    """One question per topic (``research_questions``), for the findings it covers."""
    by_question: dict[str, list[str]] = {}
    for f in findings:
        question = config.research_question(f.topic)
        if question and f.draft.priority != ReviewPriority.INFORMATION:
            by_question.setdefault(question, []).append(f.id)
    return [Question(",".join(ids), q, "guidelines") for q, ids in by_question.items()]


def spec_for(
    dossier: Dossier, findings: list[CodedFinding], research_output: dict[str, Any] | None
) -> DraftSpec:
    guidance = render_guidance(research_output)
    case = f"{dossier.case_ref}: {dossier.borrower}"
    rendered_findings = render_findings(findings)
    dossier_text = dossier.render()

    def variables(fixes: str) -> dict[str, Any]:
        return {
            "case": case,
            "dossier": dossier_text,
            "findings": rendered_findings,
            "guidance": guidance,
            "fixes": fixes,
        }

    return DraftSpec(
        task="underwriting_writer",
        prompt_id="uw-writer@1",
        output_model=UnderwritingDraft,
        variables=variables,
        evidence=f"{dossier_text}\n\nFindings:\n{rendered_findings}\n\nGuidance:\n{guidance}",
        allowed=dossier.allowed_numbers(rendered_findings, guidance),
        known_refs=dossier.refs() | {f.id for f in findings},
        known_findings={f.id for f in findings},
    )


def sections(
    dossier: Dossier,
    findings: list[CodedFinding],
    draft: dict[str, Any] | None,
    research_output: dict[str, Any] | None,
) -> dict[str, Any]:
    refs = research_output.get("references", []) if research_output else None
    out: dict[str, Any] = {
        "snapshot": snapshot(dossier),
        "guideline_references": (
            [{"passage_id": r["passage_id"], "summary": r["summary"]} for r in refs]
            if refs is not None
            else NOT_AVAILABLE
        ),
        "automated_findings_comparison": None,
        "note": NOTE,
    }
    if draft is None:
        out.update(
            conflicts=[], missing_information=[NOT_AVAILABLE], potential_risks=[NOT_AVAILABLE]
        )
        return out
    out["conflicts"] = [
        {
            "title": c["title"],
            "detail": c["detail"],
            "evidence": [_evidence(dossier, findings, r) for r in c["evidence_refs"]],
        }
        for c in draft.get("conflicts", [])
    ]
    out["missing_information"] = draft.get("missing_information", [])
    out["potential_risks"] = draft.get("potential_risks", [])
    return out


def _evidence(dossier: Dossier, findings: list[CodedFinding], ref: str) -> dict[str, Any]:
    finding = next((f for f in findings if f.id == ref), None)
    if finding is not None:
        return dict(finding.draft.evidence[0])
    fact = dossier.fact(ref)
    if fact is not None and fact.evidence:
        return {k: v for k, v in fact.evidence.items() if k != "id"}
    return {"type": "rule", "id": ref}


async def _previous_outputs(session: AsyncSession, run: AnalysisRun) -> dict[str, dict[str, Any]]:
    """The newest successful output of each agent in this run."""
    rows = (
        await session.execute(
            sa.select(AgentRun)
            .where(AgentRun.run_id == run.id, AgentRun.status == AgentRunStatus.SUCCEEDED)
            .order_by(AgentRun.attempt)
        )
    ).scalars()
    return {row.agent.value: row.output or {} for row in rows}


async def latest_underwriting_run(session: AsyncSession, case_id: uuid.UUID) -> AnalysisRun | None:
    return await session.scalar(
        sa.select(AnalysisRun)
        .where(AnalysisRun.case_id == case_id, AnalysisRun.feature == AnalysisFeature.UNDERWRITING)
        .order_by(AnalysisRun.started_at.desc(), AnalysisRun.id.desc())
        .limit(1)
    )


async def run_underwriting(
    session: AsyncSession,
    case_id: uuid.UUID,
    *,
    user_id: uuid.UUID | None = None,
    run: AnalysisRun | None = None,
    rerun: AgentName | None = None,
    config: AgentsConfig | None = None,
    gateway: Gateway | None = None,
    store: RagStore | None = None,
) -> Report:
    """Run the workflow (or one agent of it again) and write the next report version.

    Flushes; the caller commits.
    """
    config = config or get_agents_config()
    previous: dict[str, dict[str, Any]] = {}
    if rerun is not None:
        run = run or await latest_underwriting_run(session, case_id)
        if run is None:
            raise LookupError("no underwriting run to re-run an agent of")
        previous = await _previous_outputs(session, run)
        run.status = AnalysisStatus.RUNNING
    elif run is None:
        run = await report_writer.start_run(
            session,
            case_id,
            AnalysisFeature.UNDERWRITING,
            created_by=user_id,
            config_versions={"agents": {"version": config.version, "label": config.label}},
        )
    dossier = await build_dossier(
        session, case_id, UNDERWRITING_FEATURES, skip_codes=config.skip_codes
    )
    findings = build_findings(dossier, config)
    state = WorkflowState()

    if rerun in (None, AgentName.RESEARCHER) or "researcher" not in previous:
        state.research = await _logged(
            session,
            run,
            AgentName.RESEARCHER,
            lambda: research(
                questions(findings, config),
                store=store,
                gateway=gateway,
                concurrency=config.researcher_concurrency,
            ),
            state,
        )
    else:
        state.research = previous["researcher"]

    spec = spec_for(dossier, findings, state.research)
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
    conditions = [
        ConditionDraft(text=c["text"], priority=ReviewPriority(c["priority"]))
        for c in (draft or {}).get("conditions", [])
    ]
    report = await report_writer.write_report(
        session,
        run,
        ReportKind.UNDERWRITING,
        ReportDraft(
            sections=sections(dossier, findings, draft, state.research),
            findings=[f.draft for f in findings],
            conditions=conditions,
            guardrail_results={**state.guardrails, "agents_failed": state.failed},
        ),
    )
    await report_writer.finish_run(session, run, AnalysisStatus.SUCCEEDED)
    return report

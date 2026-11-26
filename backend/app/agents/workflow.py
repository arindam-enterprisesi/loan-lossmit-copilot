"""The three-agent workflow shared by the underwriting copilot and the LM recommendation.

    Researcher -> Writer -> Critic (code checks, then a reading check)
                    ^          |
                    +-- once --+   if the Critic returns fixes

The state is typed (``WorkflowState``); each agent's output is validated against its schema by
the gateway and kept in the run log (``agent_runs.output``), so one agent can be re-run alone from
the others' stored outputs. If an agent fails, the report still completes: its section says
"not available" and the run log shows the failure. The guardrails in ``guardrails`` run on the
final draft whatever the Critic said.

Plain asyncio, not LangGraph: three fixed steps with one loop do not need a graph library, and the
state, run log and re-run behave as Feature Design 6.5 describes.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.config import AgentsConfig
from app.agents.guardrails import blocked_words, check_draft, strip
from app.db.enums import AgentName, AgentRunStatus
from app.db.models import AnalysisRun
from app.llm.checks import check_figures
from app.llm.gateway import Gateway, get_gateway
from app.llm.tasks import clean_text
from app.prompts.schemas.reports import CriticVerdict
from app.rag.answer import ask
from app.rag.store import RagStore, get_rag_store
from app.services.report_writer import record_agent_run

logger = logging.getLogger(__name__)

NOT_AVAILABLE = "not available"


@dataclass(frozen=True)
class Question:
    key: str  # the finding ID or option it is for
    question: str
    source_set: str = "guidelines"


@dataclass
class WorkflowState:
    research: dict[str, Any] | None = None  # {"references": [...], "facts_to_check": [...]}
    draft: dict[str, Any] | None = None  # the Writer's final draft, after the guardrails
    critic: dict[str, Any] | None = None  # {"verdict", "fixes", "code_checks"}
    guardrails: dict[str, Any] = field(default_factory=dict)
    failed: dict[str, str] = field(default_factory=dict)  # agent -> short error


async def _logged(
    session: AsyncSession,
    run: AnalysisRun,
    agent: AgentName,
    work: Callable[[], Awaitable[tuple[dict[str, Any], dict[str, Any]]]],
    state: WorkflowState,
) -> dict[str, Any] | None:
    """Run one agent and add its attempt to the run log. ``work`` returns (output, call info)."""
    started = datetime.now(UTC)
    try:
        output, info = await work()
    except Exception as exc:
        logger.warning("agent %s failed run=%s: %s", agent.value, run.id, type(exc).__name__)
        state.failed[agent.value] = type(exc).__name__
        await record_agent_run(
            session,
            run,
            agent,
            status=AgentRunStatus.FAILED,
            error=f"{agent.value} did not complete ({type(exc).__name__})",
            started_at=started,
            finished_at=datetime.now(UTC),
        )
        return None
    await record_agent_run(
        session,
        run,
        agent,
        status=AgentRunStatus.SUCCEEDED,
        provider=info.get("provider"),
        model=info.get("model"),
        prompt_id=info.get("prompt_id"),
        output=output,
        started_at=started,
        finished_at=datetime.now(UTC),
    )
    return output


# --- Researcher ------------------------------------------------------------------------------


async def research(
    questions: Sequence[Question],
    *,
    case_facts: Sequence[str] = (),
    store: RagStore | None = None,
    gateway: Gateway | None = None,
    concurrency: int = 4,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Ask the guideline assistant one question per finding or option (Feature 5).

    Only sentences that passed the assistant's citation checks are kept, so every reference
    resolves to a retrieved passage.
    """
    store = store or get_rag_store()
    limit = asyncio.Semaphore(concurrency)

    async def one(q: Question) -> tuple[Question, Any]:
        async with limit:
            facts = case_facts if q.source_set == "regulation_x" else ()
            return q, await ask(
                q.question, q.source_set, case_facts=facts, store=store, gateway=gateway
            )

    results = await asyncio.gather(*(one(q) for q in questions))
    references: dict[str, dict[str, Any]] = {}
    facts_to_check: list[str] = []
    model: dict[str, Any] = {}
    for q, answer in results:
        model = answer.model or model
        facts_to_check += [f for f in answer.facts_to_check if f not in facts_to_check]
        by_marker = {c["marker"]: c["passage_id"] for c in answer.citations}
        for sentence in answer.sentences:
            for marker in sentence["citations"]:
                pid = by_marker[marker]
                ref = references.setdefault(
                    pid,
                    {"passage_id": pid, "summary": "", "for": [], "label": "", "source": ""},
                )
                if sentence["text"] not in ref["summary"]:
                    ref["summary"] = f"{ref['summary']} {sentence['text']}".strip()
                if q.key not in ref["for"]:
                    ref["for"].append(q.key)
        for p in answer.passages:
            if p["id"] in references:
                references[p["id"]]["label"] = p["label"]
                references[p["id"]]["source"] = f"{p['source_title']}, section {p['heading']}"
    output = {
        "questions": [{"key": q.key, "question": q.question} for q in questions],
        "references": list(references.values()),
        "facts_to_check": facts_to_check,
    }
    return output, {**model, "prompt_id": "answer@1"}


def render_guidance(research_output: dict[str, Any] | None) -> str:
    if not research_output or not research_output.get("references"):
        return "(no guidance found)"
    rows = [
        clean_text(
            f"- passage {r['passage_id']} | {r.get('source') or 'source not given'} | "
            f"{r.get('label') or 'label unknown'} | for {', '.join(r['for'])}: {r['summary']}"
        )
        for r in research_output["references"]
    ]
    if research_output.get("facts_to_check"):
        rows += [clean_text(f"- fact to check: {f}") for f in research_output["facts_to_check"]]
    return "\n".join(rows)


# --- Writer and Critic -----------------------------------------------------------------------


@dataclass
class DraftSpec:
    """What differs between the two reports: the Writer's prompt, model and checks."""

    task: str
    prompt_id: str
    output_model: type[BaseModel]
    variables: Callable[[str], dict[str, Any]]  # fixes text -> prompt variables
    evidence: str  # what the Critic reads the draft against
    allowed: set[Any]  # numbers the text may contain
    known_refs: set[str] | None = None
    known_findings: set[str] | None = None


async def write(
    spec: DraftSpec, fixes: str, gateway: Gateway | None
) -> tuple[dict[str, Any], dict[str, Any]]:
    call = await (gateway or get_gateway()).run(
        spec.task, spec.prompt_id, spec.variables(fixes), spec.output_model
    )
    info = {"provider": call.provider, "model": call.model, "prompt_id": call.prompt_id}
    return call.output.model_dump(mode="json"), info


def code_checks(
    spec: DraftSpec, draft: dict[str, Any], config: AgentsConfig
) -> list[dict[str, str]]:
    return check_draft(
        draft,
        allowed=spec.allowed,
        extra_words=config.extra_blocked_words,
        known_refs=spec.known_refs,
        known_findings=spec.known_findings,
    )


async def critique(
    spec: DraftSpec, draft: dict[str, Any], issues: list[dict[str, str]], gateway: Gateway | None
) -> tuple[dict[str, Any], dict[str, Any]]:
    checks = "\n".join(f"- {i['where']}: {i['problem']}" for i in issues) or "(none)"
    call = await (gateway or get_gateway()).run(
        "critic",
        "critic@1",
        {"evidence": spec.evidence, "code_checks": checks, "draft": json.dumps(draft, indent=1)},
        CriticVerdict,
    )
    verdict = call.output.model_dump(mode="json")
    if issues and verdict["verdict"] == "pass":
        verdict["verdict"] = "fix"  # code checks are never overruled
    verdict["code_checks"] = issues
    info = {"provider": call.provider, "model": call.model, "prompt_id": call.prompt_id}
    return verdict, info


def fixes_text(verdict: dict[str, Any] | None, issues: list[dict[str, str]]) -> str:
    rows = [f"- {i['where']}: {i['problem']}" for i in issues]
    for fix in (verdict or {}).get("fixes", []):
        rows.append(f"- {fix['where']}: {fix['problem']} Fix: {fix['fix']}")
    return "\n".join(dict.fromkeys(rows)) or "(none)"


async def write_and_check(
    session: AsyncSession,
    run: AnalysisRun,
    spec: DraftSpec,
    state: WorkflowState,
    config: AgentsConfig,
    *,
    gateway: Gateway | None = None,
    run_writer: bool = True,
    previous_draft: dict[str, Any] | None = None,
) -> None:
    """Writer, Critic, at most one return to the Writer, then the guardrails."""
    draft = previous_draft
    if run_writer or draft is None:
        draft = await _logged(
            session, run, AgentName.WRITER, lambda: write(spec, "(none)", gateway), state
        )
    if draft is None:
        state.draft = None
        return
    first: dict[str, Any] = draft
    issues = code_checks(spec, first, config)
    verdict = await _logged(
        session, run, AgentName.CRITIC, lambda: critique(spec, first, issues, gateway), state
    )
    if (verdict and verdict["verdict"] == "fix") or (verdict is None and issues):
        text = fixes_text(verdict, issues)
        redrafted = await _logged(
            session, run, AgentName.WRITER, lambda: write(spec, text, gateway), state
        )
        if redrafted is not None:
            draft = redrafted
            state.failed.pop(AgentName.WRITER.value, None)
            issues = code_checks(spec, draft, config)
    state.critic = verdict

    def still_fails(sentence: str) -> bool:
        return bool(
            check_figures(sentence, spec.allowed)
            or blocked_words(sentence, config.extra_blocked_words)
        )

    final, removed = strip(draft, issues, still_fails)
    state.draft = final
    state.guardrails = {
        "checks": [
            "every finding has evidence",
            "every figure equals a stored result",
            "no decision wording",
            "every citation resolves to a retrieved passage",
        ],
        "issues_after_critic": issues,
        "removed": removed,
        "critic_verdict": (verdict or {}).get("verdict", NOT_AVAILABLE),
        "critic_returned_draft": bool(verdict and verdict["verdict"] == "fix"),
    }

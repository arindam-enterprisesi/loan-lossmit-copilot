"""Smoke test: tiny structured-output calls through the gateway, per provider.

    uv run python -m app.llm.smoke --provider anthropic
    uv run python -m app.llm.smoke --provider all
    uv run python -m app.llm.smoke --provider gemini --check classify
    uv run python -m app.llm.smoke --provider anthropic --check extract

Checks: smoke (echo), classify, extract (Daniel Reyes's pay stub), label (his
August bank statement's transactions), hardship (Angela Whitfield's letter) and
explain (Daniel's W-2 deferral flag). The samples are synthetic.

Prints each result with tokens and latency. Exits 1 if any call fails.
Reads keys from the repo-root .env if present.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

from pydantic import BaseModel

from app.llm.config import load_llm_config
from app.llm.gateway import GatewayError, run
from app.llm.hardship import read_hardship_letter
from app.llm.income import explain_income_flags
from app.llm.samples import daniel_income_inputs, load_lines, sample_transactions
from app.llm.tasks import classify, extract, label_transactions
from app.prompts.schemas.registry import DocumentType
from app.prompts.schemas.transactions import TransactionCategory

REPO_ROOT = Path(__file__).resolve().parents[3]


class SmokeResult(BaseModel):
    echo: str
    length: int


# Synthetic samples (invented people), with the line IDs ingestion produces.
SAMPLE_PAY_STUB = load_lines("daniel_pay_stub")
SAMPLE_STATEMENT = "daniel_bank_statement_2026-08"
SAMPLE_LETTER = load_lines("angela_hardship_letter")

# What the pay stub check expects: values exactly as printed, on these lines.
# Net pay is the deliberate misprint (true net is 2,033.61); the arithmetic check in
# code is what catches it, not the model.
EXPECTED_PAY_STUB = {
    "net_pay_current": ("2,083.61", "p1-L31"),
    "gross_pay_current": ("3,070.50", "p1-L17"),
    "total_deductions_current": ("1,036.89", "p1-L25"),
    "pay_date": ("2026-10-02", "p1-L10"),
}


async def check_smoke(provider: str) -> str:
    result = await run("smoke", "smoke@1", {"word": "mortgage"}, SmokeResult, provider=provider)
    out = result.output
    status = "ok" if (out.echo, out.length) == ("mortgage", 8) else "UNEXPECTED"
    return (
        f"smoke    {status:10} {out.model_dump_json()}  model={result.model} "
        f"attempts={result.attempts} in={result.input_tokens} out={result.output_tokens} "
        f"{result.latency_ms}ms"
    )


async def check_classify(provider: str) -> str:
    outcome = await classify(SAMPLE_PAY_STUB, provider=provider)
    r, call = outcome.result, outcome.call
    status = "ok" if r.doc_type == "pay_stub" and not outcome.unknown_line_ids else "UNEXPECTED"
    return (
        f"classify {status:10} type={r.doc_type} certainty={r.certainty} "
        f"lines={r.justification_line_ids} model={call.model} attempts={call.attempts} "
        f"in={call.input_tokens} out={call.output_tokens} {call.latency_ms}ms"
    )


async def check_extract(provider: str) -> str:
    outcome = await extract(SAMPLE_PAY_STUB, DocumentType.PAY_STUB, provider=provider)
    fields = outcome.result.fields
    problems = []
    for name, (value, line) in EXPECTED_PAY_STUB.items():
        got = getattr(fields, name)
        if got.value != value or line not in got.lines:
            problems.append(f"{name}={got.value!r}@{got.lines}")
    if len(fields.earnings) != 3 or len(fields.deductions) != 6:
        problems.append(f"rows earnings={len(fields.earnings)} deductions={len(fields.deductions)}")
    if outcome.unknown_line_ids:
        problems.append(f"unknown lines {outcome.unknown_line_ids}")
    status = "ok" if not problems else "UNEXPECTED"
    calls = outcome.calls
    return (
        f"extract  {status:10} {'; '.join(problems) or 'net pay 2,083.61 @ p1-L31'} "
        f"model={calls[0].model} calls={len(calls)} "
        f"attempts={sum(c.attempts for c in calls)} in={sum(c.input_tokens for c in calls)} "
        f"out={sum(c.output_tokens for c in calls)} {max(c.latency_ms for c in calls)}ms"
    )


async def check_label(provider: str) -> str:
    transactions = sample_transactions(SAMPLE_STATEMENT)
    outcome = await label_transactions(
        transactions,
        borrower_names=["Daniel Reyes"],
        employer_names=["Cedar Valley Manufacturing, Inc."],
        provider=provider,
    )
    by_line = {lab.line_id: lab for lab in outcome.labels}
    payroll = [t.line_id for t in transactions if "PAYROLL" in t.description]
    review = [lab.line_id for lab in outcome.labels if lab.needs_review]
    ok = (
        not review
        and not outcome.unknown_line_ids
        and all(by_line[lid].category is TransactionCategory.PAYROLL_DEPOSIT for lid in payroll)
    )
    calls = outcome.calls
    return (
        f"label    {'ok' if ok else 'UNEXPECTED':10} {len(outcome.labels)} labelled, "
        f"needs review={review}, unknown={outcome.unknown_line_ids} "
        f"model={calls[0].model} calls={len(calls)} in={sum(c.input_tokens for c in calls)} "
        f"out={sum(c.output_tokens for c in calls)} {sum(c.latency_ms for c in calls)}ms"
    )


async def check_hardship(provider: str) -> str:
    outcome = await read_hardship_letter(
        SAMPLE_LETTER, application_reasons=["Reduction in income"], provider=provider
    )
    p, call = outcome.profile, outcome.call
    got = (p.primary_reason.category, p.onset.month, p.duration.category, p.intent.category)
    expected = ("reduction_in_income", "2026-07", "unknown", "keep")
    ok = got == expected and outcome.all_quotes_verified and not outcome.unknown_line_ids
    flagged = [c.path for c in outcome.flagged]
    return (
        f"hardship {'ok' if ok else 'UNEXPECTED':10} {'/'.join(str(g) for g in got)} "
        f"quotes={len(outcome.quote_checks)} flagged={flagged} model={call.model} "
        f"attempts={call.attempts} in={call.input_tokens} out={call.output_tokens} "
        f"{call.latency_ms}ms"
    )


async def check_explain(provider: str) -> str:
    flags, evidence = daniel_income_inputs()
    outcome = await explain_income_flags(flags, evidence, provider=provider)
    call = outcome.call
    cites_box12 = any("w2_2025.box12" in e.explanation.evidence_refs for e in outcome.explanations)
    flagged = sorted({f for e in outcome.explanations for f in e.flags})
    ok = cites_box12 and not flagged and not outcome.unknown_flag_codes
    return (
        f"explain  {'ok' if ok else 'UNEXPECTED':10} {len(outcome.explanations)} explanation(s), "
        f"cites Box 12={cites_box12}, flags={flagged} model={call.model} "
        f"attempts={call.attempts} in={call.input_tokens} out={call.output_tokens} "
        f"{call.latency_ms}ms"
    )


async def main(argv: list[str] | None = None) -> int:
    providers = sorted(load_llm_config().providers)
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--provider", choices=[*providers, "all"], default="all")
    parser.add_argument(
        "--check",
        choices=["smoke", "classify", "extract", "label", "hardship", "explain", "all"],
        default="all",
    )
    args = parser.parse_args(argv)

    try:
        from dotenv import load_dotenv

        load_dotenv(REPO_ROOT / ".env")
    except ImportError:
        pass

    selected = providers if args.provider == "all" else [args.provider]
    checks = {
        "smoke": check_smoke,
        "classify": check_classify,
        "extract": check_extract,
        "label": check_label,
        "hardship": check_hardship,
        "explain": check_explain,
    }
    names = list(checks) if args.check == "all" else [args.check]

    failures = 0
    for provider in selected:
        print(f"[{provider}]")
        for name in names:
            try:
                line = await checks[name](provider)
            except GatewayError as exc:
                failures += 1
                line = f"{name:8} FAILED     {exc.reason}"
            else:
                failures += "UNEXPECTED" in line
            print(f"  {line}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))

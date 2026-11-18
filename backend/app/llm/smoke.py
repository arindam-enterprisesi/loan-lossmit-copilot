"""Smoke test: tiny structured-output calls through the gateway, per provider.

    uv run python -m app.llm.smoke --provider anthropic
    uv run python -m app.llm.smoke --provider all
    uv run python -m app.llm.smoke --provider gemini --check classify

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
from app.llm.tasks import DocumentLine, classify

REPO_ROOT = Path(__file__).resolve().parents[3]


class SmokeResult(BaseModel):
    echo: str
    length: int


# Synthetic sample (not a real person): the first lines of a pay stub.
SAMPLE_PAY_STUB = [
    DocumentLine(1, 1, "NORTHWIND LOGISTICS INC."),
    DocumentLine(1, 2, "Earnings Statement"),
    DocumentLine(1, 3, "Employee: Daniel Reyes        Employee ID: 0042"),
    DocumentLine(1, 4, "Pay Period: 07/16/2026 - 07/31/2026    Pay Date: 08/05/2026"),
    DocumentLine(1, 5, "Earnings          Rate     Hours    Current     YTD"),
    DocumentLine(1, 6, "Regular           34.50    80.00    2,760.00    41,400.00"),
    DocumentLine(1, 7, "Overtime          51.75     6.00      310.50     3,105.00"),
    DocumentLine(1, 8, "Gross Pay                           3,070.50    44,505.00"),
    DocumentLine(1, 9, "Deductions                          1,036.89    15,031.45"),
    DocumentLine(1, 10, "Net Pay                             2,033.61    29,473.55"),
]


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


async def main(argv: list[str] | None = None) -> int:
    providers = sorted(load_llm_config().providers)
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--provider", choices=[*providers, "all"], default="all")
    parser.add_argument("--check", choices=["smoke", "classify", "all"], default="all")
    args = parser.parse_args(argv)

    try:
        from dotenv import load_dotenv

        load_dotenv(REPO_ROOT / ".env")
    except ImportError:
        pass

    selected = providers if args.provider == "all" else [args.provider]
    checks = {"smoke": check_smoke, "classify": check_classify}
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

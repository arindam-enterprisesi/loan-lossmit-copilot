"""Provider evaluation (D9): the same checks on each provider, timed, as a Markdown table.

    uv run python -m app.llm.evaluate --out ../docs/provider-evaluation.md

Each check is one of the smoke checks (``app.llm.smoke``) on the synthetic samples, so the
expected answer is known: classify the pay stub, extract its net pay at line p1-L31, label the
August statement, read Angela's letter with every quote verified, explain the W-2 deferral
flag citing Box 12, plus a guideline answer whose citations survive the code checks. A provider
without credentials is reported as "no credentials", not as a failure of the model.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from app.llm.config import load_llm_config
from app.llm.env import load_provider_env
from app.llm.smoke import (
    check_classify,
    check_explain,
    check_extract,
    check_hardship,
    check_label,
)


async def check_guideline(provider: str) -> str:
    from app.rag.answer import ask

    answer = await ask("How is overtime income evaluated?", "all", provider=provider)
    cited = {c["passage_id"] for c in answer.citations}
    ok = {"fnma-sg.B3-3.1-01.variable", "fhlmc-guide.5303.1"} <= cited
    return (
        f"guideline {'ok' if ok else 'UNEXPECTED':10} {len(answer.sentences)} sentences, "
        f"{answer.removed_sentences} removed, cites {', '.join(sorted(cited)) or 'nothing'}"
    )


CHECKS: dict[str, Callable[[str], Awaitable[str]]] = {
    "classify": check_classify,
    "extract": check_extract,
    "label": check_label,
    "hardship": check_hardship,
    "explain": check_explain,
    "guideline": check_guideline,
}


@dataclass
class Result:
    provider: str
    check: str
    passed: bool | None  # None: not run (no credentials)
    seconds: float
    detail: str


async def run_one(provider: str, name: str) -> Result:
    started = time.perf_counter()
    try:
        line = await CHECKS[name](provider)
    except Exception as exc:  # the gateway's error names the cause, never document text
        reason = str(exc).splitlines()[0][:160]
        credentials = "credentials" in reason or "AWS:" in reason or "authentication" in reason
        return Result(provider, name, None if credentials else False, 0.0, reason)
    return Result(
        provider,
        name,
        " ok " in f" {line} ",
        time.perf_counter() - started,
        line.split(None, 2)[-1],
    )


def table(results: list[Result], models: dict[str, str]) -> str:
    providers = list(dict.fromkeys(r.provider for r in results))
    rows = [
        f"# Provider evaluation ({date.today().isoformat()})",
        "",
        "Same checks on each provider, on the synthetic samples (`python -m app.llm.evaluate`).",
        "A pass means the output matched the known answer and passed the code checks.",
        "",
        "| Check | " + " | ".join(f"{p} ({models.get(p, '?')})" for p in providers) + " |",
        "| --- | " + " | ".join("---" for _ in providers) + " |",
    ]
    for name in CHECKS:
        cells = []
        for p in providers:
            r = next(x for x in results if x.provider == p and x.check == name)
            mark = "no credentials" if r.passed is None else ("pass" if r.passed else "FAIL")
            cells.append(f"{mark}, {r.seconds:.1f} s" if r.passed is not None else mark)
        rows.append(f"| {name} | " + " | ".join(cells) + " |")
    rows += ["", "Details:", ""]
    rows += [f"- {r.provider} / {r.check}: {r.detail}" for r in results]
    return "\n".join(rows) + "\n"


async def evaluate(providers: list[str]) -> list[Result]:
    results = []
    for provider in providers:
        for name in CHECKS:
            results.append(await run_one(provider, name))
    return results


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--provider", nargs="+", default=["anthropic", "bedrock"])
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args(argv)
    load_provider_env()
    config = load_llm_config()
    models = {p: config.providers[p].model for p in args.provider if p in config.providers}
    text = table(asyncio.run(evaluate(args.provider)), models)
    if args.out:
        args.out.write_text(text, encoding="utf-8", newline="\n")
    print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""Smoke test: one tiny structured-output call through the gateway.

    uv run python -m app.llm.smoke

D2 adds --provider <name> once all four adapters exist.
"""

from __future__ import annotations

import asyncio

from pydantic import BaseModel

from app.llm.gateway import run


class SmokeResult(BaseModel):
    echo: str
    length: int


async def main() -> None:
    result = await run("smoke", "smoke@1", {"word": "mortgage"}, SmokeResult)
    print(result.output.model_dump_json())
    print(
        f"provider={result.provider} model={result.model} attempts={result.attempts} "
        f"tokens_in={result.input_tokens} tokens_out={result.output_tokens} "
        f"latency_ms={result.latency_ms}"
    )


if __name__ == "__main__":
    asyncio.run(main())

"""Real provider calls. Run with `uv run pytest -m live`; each provider skips without credentials.

Keys are read from the environment or the repo-root .env.
"""

import os
from pathlib import Path

import pytest

from app.llm.config import load_llm_config
from app.llm.gateway import Gateway, default_adapters
from app.llm.smoke import SAMPLE_PAY_STUB, SmokeResult
from app.llm.tasks import classify

try:
    from dotenv import load_dotenv

    load_dotenv(Path(__file__).resolve().parents[3] / ".env")
except ImportError:
    pass


def _has_aws() -> bool:
    has_region = bool(os.environ.get("AWS_REGION") or os.environ.get("AWS_DEFAULT_REGION"))
    has_creds = bool(os.environ.get("AWS_ACCESS_KEY_ID") or os.environ.get("AWS_PROFILE"))
    return has_region and has_creds


CREDENTIALS = {
    "anthropic": lambda: bool(os.environ.get("ANTHROPIC_API_KEY")),
    "bedrock": _has_aws,
    "gemini": lambda: bool(os.environ.get("GOOGLE_API_KEY")),
    "openai": lambda: bool(os.environ.get("OPENAI_API_KEY")),
}

PROVIDERS = [
    pytest.param(name, marks=pytest.mark.skipif(not has(), reason=f"no {name} credentials"))
    for name, has in CREDENTIALS.items()
]


@pytest.fixture(scope="module")
def gateway() -> Gateway:
    return Gateway(default_adapters(), load_llm_config())


@pytest.mark.live
@pytest.mark.parametrize("provider", PROVIDERS)
async def test_smoke(gateway: Gateway, provider: str) -> None:
    result = await gateway.run(
        "smoke", "smoke@1", {"word": "mortgage"}, SmokeResult, provider=provider
    )
    assert result.output == SmokeResult(echo="mortgage", length=8)
    assert result.provider == provider
    assert result.input_tokens > 0


@pytest.mark.live
@pytest.mark.parametrize("provider", PROVIDERS)
async def test_classify_pay_stub(gateway: Gateway, provider: str) -> None:
    outcome = await classify(SAMPLE_PAY_STUB, provider=provider, gateway=gateway)
    assert outcome.result.doc_type == "pay_stub"
    assert outcome.result.justification_line_ids
    assert outcome.unknown_line_ids == []

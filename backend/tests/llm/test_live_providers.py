"""Real provider calls. Run with `uv run pytest -m live`; each provider skips without credentials.

Keys are read from the environment or the repo-root .env.
"""

import os
from pathlib import Path

import pytest

from app.llm.config import load_llm_config
from app.llm.gateway import Gateway, default_adapters
from app.llm.samples import sample_transactions
from app.llm.smoke import (
    EXPECTED_PAY_STUB,
    SAMPLE_PAY_STUB,
    SAMPLE_STATEMENT,
    SmokeResult,
)
from app.llm.tasks import classify, extract, iter_extracted, label_transactions
from app.prompts.schemas.registry import DocumentType
from app.prompts.schemas.transactions import TransactionCategory

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


@pytest.mark.live
@pytest.mark.parametrize("provider", PROVIDERS)
async def test_extract_daniel_pay_stub(gateway: Gateway, provider: str) -> None:
    """D3 done-when: every field of Daniel's pay stub, with line IDs."""
    outcome = await extract(
        SAMPLE_PAY_STUB, DocumentType.PAY_STUB, provider=provider, gateway=gateway
    )
    fields = outcome.result.fields
    for name, (value, line) in EXPECTED_PAY_STUB.items():
        got = getattr(fields, name)
        assert got.value == value, name
        assert line in got.lines, name
    assert len(fields.earnings) == 3
    assert len(fields.deductions) == 6
    assert outcome.unknown_line_ids == []
    # Every value found carries the lines it came from. (Hours and rate on the bonus row
    # are not printed, so some fields are rightly null.)
    found = [(path, f) for path, f in iter_extracted(fields) if f.value is not None]
    assert len(found) >= 40
    assert all(f.lines for _, f in found)


@pytest.mark.live
@pytest.mark.parametrize("provider", PROVIDERS)
async def test_label_daniel_august_transactions(gateway: Gateway, provider: str) -> None:
    transactions = sample_transactions(SAMPLE_STATEMENT)
    outcome = await label_transactions(
        transactions,
        borrower_names=["Daniel Reyes"],
        employer_names=["Cedar Valley Manufacturing, Inc."],
        provider=provider,
        gateway=gateway,
    )
    assert outcome.unknown_line_ids == []
    assert not [lab.line_id for lab in outcome.labels if lab.needs_review]
    by_line = {lab.line_id: lab.category for lab in outcome.labels}
    assert by_line["p1-L20"] is TransactionCategory.PAYROLL_DEPOSIT
    assert by_line["p1-L14"] is TransactionCategory.HOUSING_PAYMENT

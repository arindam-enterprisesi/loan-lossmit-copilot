import json
import logging
from dataclasses import dataclass, field
from pathlib import Path

import pytest
from pydantic import BaseModel

from app.llm.config import LLMConfig, TaskConfig
from app.llm.gateway import Gateway, GatewayError
from app.llm.types import AdapterRequest, AdapterResponse, ProviderCallError


class Answer(BaseModel):
    echo: str
    length: int


@dataclass
class FakeAdapter:
    """Returns queued responses in order and records every request."""

    responses: list[AdapterResponse | Exception]
    name: str = "fake"
    requests: list[AdapterRequest] = field(default_factory=list)

    async def complete(self, request: AdapterRequest) -> AdapterResponse:
        self.requests.append(request)
        item = self.responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


@pytest.fixture
def prompts_dir(tmp_path: Path) -> Path:
    (tmp_path / "echo@1.md").write_text(
        "---\ndescription: test\n---\n## system\nBe exact.\n## user\nEcho {{word}}.\n",
        encoding="utf-8",
    )
    return tmp_path


@pytest.fixture
def config() -> LLMConfig:
    return LLMConfig(
        version="test",
        label="illustrative",
        defaults=TaskConfig(provider="fake", model="fake-model", options={"effort": "low"}),
        tasks={"special": {"model": "other-model", "options": {"effort": "high"}}},
    )


VALID = AdapterResponse(text='{"echo": "loan", "length": 4}', input_tokens=10, output_tokens=5)
INVALID = AdapterResponse(text='{"echo": "loan"}', input_tokens=10, output_tokens=3)


async def test_success_returns_validated_model(prompts_dir: Path, config: LLMConfig) -> None:
    adapter = FakeAdapter([VALID])
    gateway = Gateway({"fake": adapter}, config, prompts_dir)

    result = await gateway.run("smoke", "echo@1", {"word": "loan"}, Answer)

    assert result.output == Answer(echo="loan", length=4)
    assert result.attempts == 1
    assert (result.provider, result.model) == ("fake", "fake-model")
    assert (result.input_tokens, result.output_tokens) == (10, 5)
    request = adapter.requests[0]
    assert request.system == "Be exact."
    assert request.messages[0].content == "Echo loan."
    assert request.temperature == 0
    assert request.options == {"effort": "low"}


async def test_one_retry_with_validation_error(prompts_dir: Path, config: LLMConfig) -> None:
    adapter = FakeAdapter([INVALID, VALID])
    gateway = Gateway({"fake": adapter}, config, prompts_dir)

    result = await gateway.run("smoke", "echo@1", {"word": "loan"}, Answer)

    assert result.attempts == 2
    assert (result.input_tokens, result.output_tokens) == (20, 8)
    retry = adapter.requests[1].messages
    assert [m.role for m in retry] == ["user", "assistant", "user"]
    assert "length" in retry[-1].content
    assert "did not match the required output schema" in retry[-1].content


async def test_failure_after_retry_raises(prompts_dir: Path, config: LLMConfig) -> None:
    adapter = FakeAdapter([INVALID, INVALID])
    gateway = Gateway({"fake": adapter}, config, prompts_dir)

    with pytest.raises(GatewayError, match="after 2 attempts"):
        await gateway.run("smoke", "echo@1", {"word": "loan"}, Answer)
    assert len(adapter.requests) == 2


async def test_refusal_is_not_retried(prompts_dir: Path, config: LLMConfig) -> None:
    adapter = FakeAdapter([AdapterResponse(text="", refused=True)])
    gateway = Gateway({"fake": adapter}, config, prompts_dir)

    with pytest.raises(GatewayError, match="declined"):
        await gateway.run("smoke", "echo@1", {"word": "loan"}, Answer)
    assert len(adapter.requests) == 1


async def test_provider_error_becomes_gateway_error(prompts_dir: Path, config: LLMConfig) -> None:
    adapter = FakeAdapter([ProviderCallError("fake", "HTTP 503", retryable=True)])
    gateway = Gateway({"fake": adapter}, config, prompts_dir)

    with pytest.raises(GatewayError, match="HTTP 503"):
        await gateway.run("smoke", "echo@1", {"word": "loan"}, Answer)


async def test_task_override_and_unknown_provider(prompts_dir: Path, config: LLMConfig) -> None:
    adapter = FakeAdapter([VALID])
    gateway = Gateway({"fake": adapter}, config, prompts_dir)
    result = await gateway.run("special", "echo@1", {"word": "loan"}, Answer)
    assert result.model == "other-model"
    assert adapter.requests[0].options == {"effort": "high"}

    no_adapter = Gateway({}, config, prompts_dir)
    with pytest.raises(GatewayError, match="no adapter for provider 'fake'"):
        await no_adapter.run("smoke", "echo@1", {"word": "loan"}, Answer)


async def test_prompt_errors_surface_as_gateway_errors(
    prompts_dir: Path, config: LLMConfig
) -> None:
    gateway = Gateway({"fake": FakeAdapter([])}, config, prompts_dir)
    with pytest.raises(GatewayError, match="missing variables"):
        await gateway.run("smoke", "echo@1", {}, Answer)
    with pytest.raises(GatewayError, match="invalid prompt id"):
        await gateway.run("smoke", "../secrets@1", {"word": "x"}, Answer)


async def test_call_log_has_metadata_but_no_document_text(
    prompts_dir: Path, config: LLMConfig, caplog: pytest.LogCaptureFixture
) -> None:
    secret = "SSN 123-45-6789"
    adapter = FakeAdapter([INVALID, VALID])
    gateway = Gateway({"fake": adapter}, config, prompts_dir)

    with caplog.at_level(logging.INFO, logger="app.llm.calls"):
        await gateway.run("smoke", "echo@1", {"word": secret}, Answer)

    records = [json.loads(r.getMessage()) for r in caplog.records]
    assert [r["success"] for r in records] == [False, True]
    for record in records:
        assert set(record) >= {
            "task",
            "prompt_id",
            "provider",
            "model",
            "input_tokens",
            "output_tokens",
            "latency_ms",
            "success",
        }
    assert secret not in caplog.text

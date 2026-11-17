import os
from types import SimpleNamespace
from typing import Any

import pytest
from pydantic import BaseModel

from app.llm.adapters.anthropic import FALLBACK_BETA, AnthropicAdapter
from app.llm.config import LLMConfig, TaskConfig
from app.llm.gateway import Gateway
from app.llm.smoke import SmokeResult
from app.llm.types import AdapterRequest, Message


class Out(BaseModel):
    value: str


def make_request(**options: Any) -> AdapterRequest:
    return AdapterRequest(
        model="claude-opus-5-5",
        system="sys",
        messages=[Message("user", "hi")],
        output_model=Out,
        max_tokens=100,
        temperature=0,
        options=options,
    )


class FakeMessages:
    def __init__(self, stop_reason: str = "end_turn") -> None:
        self.calls: list[dict[str, Any]] = []
        self.stop_reason = stop_reason

    async def create(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        return SimpleNamespace(
            content=[SimpleNamespace(type="text", text='{"value": "x"}')],
            usage=SimpleNamespace(input_tokens=7, output_tokens=3),
            stop_reason=self.stop_reason,
        )


def fake_client(stop_reason: str = "end_turn") -> Any:
    messages = FakeMessages(stop_reason)
    beta_messages = FakeMessages(stop_reason)
    return SimpleNamespace(messages=messages, beta=SimpleNamespace(messages=beta_messages))


async def test_request_shape_has_schema_and_no_temperature() -> None:
    client = fake_client()
    response = await AnthropicAdapter(client).complete(make_request(effort="low"))

    sent = client.messages.calls[0]
    assert "temperature" not in sent
    assert sent["output_config"]["effort"] == "low"
    assert sent["output_config"]["format"]["type"] == "json_schema"
    assert sent["system"] == "sys"
    assert response.text == '{"value": "x"}'
    assert (response.input_tokens, response.output_tokens) == (7, 3)
    assert not response.refused


async def test_fallbacks_use_beta_endpoint() -> None:
    client = fake_client()
    await AnthropicAdapter(client).complete(make_request(fallbacks="default"))
    sent = client.beta.messages.calls[0]
    assert sent["betas"] == [FALLBACK_BETA]
    assert sent["fallbacks"] == "default"
    assert client.messages.calls == []


async def test_refusal_flag() -> None:
    response = await AnthropicAdapter(fake_client("refusal")).complete(make_request())
    assert response.refused


@pytest.mark.live
@pytest.mark.skipif(not os.environ.get("ANTHROPIC_API_KEY"), reason="ANTHROPIC_API_KEY not set")
async def test_live_smoke_call() -> None:
    config = LLMConfig(
        version="live",
        label="illustrative",
        defaults=TaskConfig(
            provider="anthropic",
            model="claude-opus-5-5",
            max_tokens=1024,
            options={"effort": "low"},
        ),
    )
    gateway = Gateway({"anthropic": AnthropicAdapter()}, config)
    result = await gateway.run("smoke", "smoke@1", {"word": "mortgage"}, SmokeResult)
    assert result.output == SmokeResult(echo="mortgage", length=8)

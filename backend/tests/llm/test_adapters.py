from types import SimpleNamespace
from typing import Any

import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from pydantic import BaseModel

from app.llm.adapters.anthropic import FALLBACK_BETA, AnthropicAdapter, BedrockClaudeAdapter
from app.llm.adapters.langchain import (
    LangChainAdapter,
    gemini_chat_model,
    openai_chat_model,
)
from app.llm.types import AdapterRequest, Message, ProviderCallError


class Out(BaseModel):
    value: str


def make_request(temperature: float | None = 0, **options: Any) -> AdapterRequest:
    return AdapterRequest(
        model="test-model",
        system="sys",
        messages=[Message("user", "hi"), Message("assistant", "bad"), Message("user", "fix")],
        output_model=Out,
        max_tokens=100,
        temperature=temperature,
        options=options,
    )


# ---------- Claude API and Bedrock ----------


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
    return SimpleNamespace(
        messages=FakeMessages(stop_reason),
        beta=SimpleNamespace(messages=FakeMessages(stop_reason)),
    )


async def test_claude_request_has_schema_and_no_temperature() -> None:
    client = fake_client()
    response = await AnthropicAdapter(client).complete(make_request(effort="low"))

    sent = client.messages.calls[0]
    assert "temperature" not in sent
    assert sent["output_config"]["effort"] == "low"
    assert sent["output_config"]["format"]["type"] == "json_schema"
    assert sent["system"] == "sys"
    assert [m["role"] for m in sent["messages"]] == ["user", "assistant", "user"]
    assert response.text == '{"value": "x"}'
    assert (response.input_tokens, response.output_tokens) == (7, 3)
    assert not response.refused


async def test_claude_fallbacks_use_beta_endpoint() -> None:
    client = fake_client()
    await AnthropicAdapter(client).complete(make_request(fallbacks="default"))
    sent = client.beta.messages.calls[0]
    assert sent["betas"] == [FALLBACK_BETA]
    assert sent["fallbacks"] == "default"
    assert client.messages.calls == []


async def test_claude_refusal_and_truncation_flags() -> None:
    assert (await AnthropicAdapter(fake_client("refusal")).complete(make_request())).refused
    assert (await AnthropicAdapter(fake_client("max_tokens")).complete(make_request())).truncated


async def test_bedrock_ignores_fallbacks_and_needs_region(monkeypatch: pytest.MonkeyPatch) -> None:
    client = fake_client()
    await BedrockClaudeAdapter(client).complete(make_request(fallbacks="default"))
    assert client.beta.messages.calls == []
    assert len(client.messages.calls) == 1

    monkeypatch.delenv("AWS_REGION", raising=False)
    monkeypatch.delenv("AWS_DEFAULT_REGION", raising=False)
    with pytest.raises(ProviderCallError, match="AWS_REGION"):
        await BedrockClaudeAdapter().complete(make_request())


async def test_bedrock_builds_the_runtime_client_not_mantle(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # bedrock-runtime (InvokeModel) is the endpoint that works with the models the AWS admin named
    # (Sonnet 4.6, Haiku 4.5); the Mantle endpoint needs a separate permission that was not granted.
    monkeypatch.setenv("AWS_REGION", "ap-south-1")
    client = BedrockClaudeAdapter()._create_client()
    assert type(client).__name__ == "AsyncAnthropicBedrock"
    assert client.aws_region == "ap-south-1"
    assert str(client.base_url).startswith("https://bedrock-runtime.ap-south-1.amazonaws.com")


async def test_bedrock_region_falls_back_to_aws_default_region(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("AWS_REGION", raising=False)
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")
    assert BedrockClaudeAdapter()._create_client().aws_region == "us-east-1"


# ---------- Gemini and OpenAI (LangChain) ----------


class FakeChatModel:
    def __init__(self, raw: AIMessage | Exception) -> None:
        self.raw = raw
        self.structured_args: tuple[Any, ...] = ()
        self.structured_kwargs: dict[str, Any] = {}
        self.invoked_with: list[Any] = []

    def with_structured_output(self, *args: Any, **kwargs: Any) -> "FakeChatModel":
        self.structured_args, self.structured_kwargs = args, kwargs
        return self

    async def ainvoke(self, messages: list[Any]) -> dict[str, Any]:
        self.invoked_with = messages
        if isinstance(self.raw, Exception):
            raise self.raw
        return {"raw": self.raw, "parsed": None, "parsing_error": None}


def raw_message(content: Any = '{"value": "x"}', finish: str = "stop", **extra: Any) -> AIMessage:
    return AIMessage(
        content=content,
        usage_metadata={"input_tokens": 11, "output_tokens": 4, "total_tokens": 15},
        response_metadata={"finish_reason": finish},
        **extra,
    )


async def test_langchain_adapter_maps_messages_text_and_usage() -> None:
    model = FakeChatModel(raw_message(content=[{"type": "text", "text": '{"value": "x"}'}]))
    adapter = LangChainAdapter("gemini", lambda req: model)

    response = await adapter.complete(make_request())

    assert model.structured_args == (Out,)
    assert model.structured_kwargs == {"method": "json_schema", "include_raw": True}
    assert [type(m) for m in model.invoked_with] == [
        SystemMessage,
        HumanMessage,
        AIMessage,
        HumanMessage,
    ]
    assert response.text == '{"value": "x"}'
    assert (response.input_tokens, response.output_tokens) == (11, 4)
    assert not response.refused
    assert not response.truncated


async def test_langchain_adapter_flags_truncation_and_refusal() -> None:
    truncated = LangChainAdapter("openai", lambda req: FakeChatModel(raw_message(finish="length")))
    assert (await truncated.complete(make_request())).truncated

    refusal = raw_message(content="", additional_kwargs={"refusal": "I can't help with that."})
    refused = LangChainAdapter("openai", lambda req: FakeChatModel(refusal))
    assert (await refused.complete(make_request())).refused


async def test_langchain_errors_become_provider_errors_without_message_text() -> None:
    class RateLimited(Exception):
        status_code = 429

    adapter = LangChainAdapter("openai", lambda req: FakeChatModel(RateLimited("secret text")))
    with pytest.raises(ProviderCallError) as info:
        await adapter.complete(make_request())
    assert info.value.retryable
    assert "secret text" not in str(info.value)
    assert "RateLimited (HTTP 429)" in str(info.value)


def test_openai_and_gemini_model_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("GOOGLE_API_KEY", "test-key")

    openai = openai_chat_model(make_request(temperature=None, reasoning_effort="low"))
    assert openai.model_name == "test-model"
    assert openai.max_tokens == 100
    assert openai.temperature is None
    assert openai.reasoning_effort == "low"

    gemini = gemini_chat_model(make_request(temperature=0, thinking_budget=0))
    assert gemini.model.endswith("test-model")
    assert gemini.temperature == 0
    assert gemini.max_output_tokens == 100
    assert gemini.thinking_budget == 0


async def test_claude_missing_credentials_is_a_provider_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for var in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_PROFILE"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("ANTHROPIC_CONFIG_DIR", "/nonexistent-anthropic-config")
    with pytest.raises(ProviderCallError, match="no credentials"):
        await AnthropicAdapter().complete(make_request())


async def test_langchain_missing_key_names_the_variable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    with pytest.raises(ProviderCallError, match="GOOGLE_API_KEY is not set"):
        await LangChainAdapter("gemini", gemini_chat_model).complete(make_request())

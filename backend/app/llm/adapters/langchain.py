"""Gemini and OpenAI adapters through LangChain chat models with structured output.

Both use ``with_structured_output(method="json_schema", include_raw=True)``:
the provider constrains the reply to the schema, and the gateway validates the
raw text itself, so all four providers share one validation and retry path.

Task options read from config (all optional):
  openai:  reasoning_effort (minimal | low | medium | high)
  gemini:  thinking_budget (tokens; 0 turns thinking off where the model allows)
"""

from __future__ import annotations

import os
from collections.abc import Callable
from typing import Any

from app.llm.types import AdapterRequest, AdapterResponse, ProviderCallError

ChatModelFactory = Callable[[AdapterRequest], Any]

_TRUNCATED_REASONS = {"length", "max_tokens", "MAX_TOKENS"}
_REFUSED_REASONS = {"content_filter", "SAFETY", "PROHIBITED_CONTENT", "BLOCKLIST", "RECITATION"}


def _to_langchain_messages(request: AdapterRequest) -> list[Any]:
    from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

    messages: list[Any] = [SystemMessage(request.system)] if request.system else []
    for m in request.messages:
        messages.append(HumanMessage(m.content) if m.role == "user" else AIMessage(m.content))
    return messages


class LangChainAdapter:
    def __init__(self, name: str, factory: ChatModelFactory) -> None:
        self.name = name
        self._factory = factory

    async def complete(self, request: AdapterRequest) -> AdapterResponse:
        try:
            chat_model = self._factory(request)
            runnable = chat_model.with_structured_output(
                request.output_model, method="json_schema", include_raw=True
            )
            result = await runnable.ainvoke(_to_langchain_messages(request))
        except ProviderCallError:
            raise
        except Exception as exc:
            # LangChain integrations raise each SDK's own error types. Report the
            # type only: provider messages can echo request content.
            status = getattr(exc, "status_code", None) or getattr(exc, "code", None)
            reason = type(exc).__name__ + (f" (HTTP {status})" if status else "")
            retryable = isinstance(status, int) and (status == 429 or status >= 500)
            raise ProviderCallError(self.name, reason, retryable=retryable) from exc

        raw = result["raw"]
        usage = getattr(raw, "usage_metadata", None) or {}
        metadata = getattr(raw, "response_metadata", None) or {}
        finish = str(metadata.get("finish_reason") or metadata.get("stop_reason") or "")
        refusal = (getattr(raw, "additional_kwargs", None) or {}).get("refusal")
        return AdapterResponse(
            text=raw.text,
            input_tokens=int(usage.get("input_tokens", 0)),
            output_tokens=int(usage.get("output_tokens", 0)),
            refused=bool(refusal) or finish in _REFUSED_REASONS,
            truncated=finish in _TRUNCATED_REASONS,
        )


def _require_env(provider: str, var: str) -> None:
    if not os.environ.get(var):
        raise ProviderCallError(provider, f"{var} is not set")


def openai_chat_model(request: AdapterRequest) -> Any:
    from langchain_openai import ChatOpenAI

    _require_env("openai", "OPENAI_API_KEY")

    kwargs: dict[str, Any] = {"model": request.model, "max_tokens": request.max_tokens}
    if request.temperature is not None:
        kwargs["temperature"] = request.temperature
    if effort := request.options.get("reasoning_effort"):
        kwargs["reasoning_effort"] = effort
    return ChatOpenAI(**kwargs)  # reads OPENAI_API_KEY


def gemini_chat_model(request: AdapterRequest) -> Any:
    from langchain_google_genai import ChatGoogleGenerativeAI

    _require_env("gemini", "GOOGLE_API_KEY")

    kwargs: dict[str, Any] = {"model": request.model, "max_output_tokens": request.max_tokens}
    if request.temperature is not None:
        kwargs["temperature"] = request.temperature
    if (budget := request.options.get("thinking_budget")) is not None:
        kwargs["thinking_budget"] = budget
    return ChatGoogleGenerativeAI(**kwargs)  # reads GOOGLE_API_KEY


def openai_adapter() -> LangChainAdapter:
    return LangChainAdapter("openai", openai_chat_model)


def gemini_adapter() -> LangChainAdapter:
    return LangChainAdapter("gemini", gemini_chat_model)

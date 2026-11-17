"""Claude API adapter (official ``anthropic`` SDK, structured outputs).

Why not LangChain here: current Claude models reject sampling parameters
(``temperature``) and forced ``tool_choice``, which LangChain's default
``with_structured_output`` relies on. The SDK's ``output_config.format``
JSON-schema mode constrains the reply to the schema directly, and the gateway
still validates it with Pydantic.

Task options read from config (all optional):
  effort:    low | medium | high | xhigh | max
  fallbacks: "default" to enable server-side refusal fallback (beta)
"""

from __future__ import annotations

from typing import Any

import anthropic
from anthropic import AsyncAnthropic, transform_schema

from app.llm.types import AdapterRequest, AdapterResponse, ProviderCallError

FALLBACK_BETA = "server-side-fallback-2026-07-01"


class AnthropicAdapter:
    name = "anthropic"

    def __init__(self, client: AsyncAnthropic | None = None) -> None:
        self._client = client

    def _get_client(self) -> AsyncAnthropic:
        if self._client is None:
            # Reads ANTHROPIC_API_KEY (or an `ant auth login` profile).
            self._client = AsyncAnthropic()
        return self._client

    def build_params(self, request: AdapterRequest) -> dict[str, Any]:
        output_config: dict[str, Any] = {
            "format": {
                "type": "json_schema",
                "schema": transform_schema(request.output_model.model_json_schema()),
            }
        }
        if effort := request.options.get("effort"):
            output_config["effort"] = effort
        params: dict[str, Any] = {
            "model": request.model,
            "max_tokens": request.max_tokens,
            "messages": [{"role": m.role, "content": m.content} for m in request.messages],
            "output_config": output_config,
        }
        if request.system:
            params["system"] = request.system
        # request.temperature is intentionally not sent: current Claude models
        # return 400 for sampling parameters. Determinism comes from the schema.
        return params

    async def complete(self, request: AdapterRequest) -> AdapterResponse:
        client = self._get_client()
        params = self.build_params(request)
        fallbacks = request.options.get("fallbacks")
        try:
            if fallbacks:
                response: Any = await client.beta.messages.create(
                    **params, betas=[FALLBACK_BETA], fallbacks=fallbacks
                )
            else:
                response = await client.messages.create(**params)
        except anthropic.RateLimitError as exc:
            raise ProviderCallError(self.name, "rate limited", retryable=True) from exc
        except anthropic.APIStatusError as exc:
            raise ProviderCallError(
                self.name, f"HTTP {exc.status_code}", retryable=exc.status_code >= 500
            ) from exc
        except anthropic.APIConnectionError as exc:
            raise ProviderCallError(self.name, "connection error", retryable=True) from exc

        text = "".join(block.text for block in response.content if block.type == "text")
        usage = response.usage
        return AdapterResponse(
            text=text,
            input_tokens=usage.input_tokens or 0,
            output_tokens=usage.output_tokens or 0,
            refused=response.stop_reason == "refusal",
            truncated=response.stop_reason == "max_tokens",
        )

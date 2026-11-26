"""Claude adapters: Claude API and Claude on Amazon Bedrock (official ``anthropic`` SDK).

Why not LangChain here: current Claude models reject sampling parameters
(``temperature``) and forced ``tool_choice``, which LangChain's default
structured output relies on. The SDK's ``output_config.format`` JSON-schema
mode constrains the reply to the schema directly, and the gateway still
validates it with Pydantic. Bedrock uses the same Messages API through the
SDK's bedrock-runtime client (InvokeModel), so both providers share one request
builder.

Task options read from config (all optional):
  effort:    low | medium | high | xhigh | max
  fallbacks: "default" to enable server-side refusal fallback (Claude API only, beta)
"""

from __future__ import annotations

import os
from typing import Any

import anthropic
from anthropic import AsyncAnthropic, AsyncAnthropicBedrock, transform_schema

from app.llm.types import AdapterRequest, AdapterResponse, ProviderCallError

FALLBACK_BETA = "server-side-fallback-2026-07-01"


class AnthropicAdapter:
    name = "anthropic"
    supports_server_fallbacks = True

    def __init__(self, client: Any | None = None) -> None:
        self._client = client

    def _create_client(self) -> Any:
        # Reads ANTHROPIC_API_KEY (or an `ant auth login` profile).
        return AsyncAnthropic()

    def _get_client(self) -> Any:
        if self._client is None:
            self._client = self._create_client()
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
        params = self.build_params(request)
        fallbacks = request.options.get("fallbacks") if self.supports_server_fallbacks else None
        try:
            client = self._get_client()
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
        except anthropic.CredentialsError as exc:
            raise ProviderCallError(self.name, "no credentials configured") from exc
        except anthropic.AnthropicError as exc:
            raise ProviderCallError(self.name, type(exc).__name__) from exc
        except TypeError as exc:
            # The SDK raises TypeError at request time when no credentials resolve.
            if "authentication" not in str(exc):
                raise
            raise ProviderCallError(self.name, "no credentials configured") from exc
        except Exception as exc:
            # Bedrock signs requests with botocore, whose errors (no credentials, a profile that
            # does not exist, a bad region) are not AnthropicError. Name the class, never the text.
            if type(exc).__module__.split(".")[0] != "botocore":
                raise
            raise ProviderCallError(self.name, f"AWS: {type(exc).__name__}") from exc

        text = "".join(block.text for block in response.content if block.type == "text")
        usage = response.usage
        return AdapterResponse(
            text=text,
            input_tokens=usage.input_tokens or 0,
            output_tokens=usage.output_tokens or 0,
            refused=response.stop_reason == "refusal",
            truncated=response.stop_reason == "max_tokens",
        )


class BedrockClaudeAdapter(AnthropicAdapter):
    """Claude on Amazon Bedrock via the bedrock-runtime endpoint (InvokeModel).

    Credentials come from the standard AWS chain (env keys, AWS_PROFILE, SSO);
    the region from AWS_REGION. Newer models are called through an inference
    profile, so model IDs are usually profile IDs supplied by the AWS admin, for
    example ``global.anthropic.claude-sonnet-4-6``. The IAM user needs
    ``bedrock:InvokeModel`` on that profile.

    This was the SDK's Mantle client (``bedrock-mantle:CreateInference``) until
    2026-11-23. The project's IAM user was never allowed that action, while
    InvokeModel works for the models the AWS admin named, with the same Messages
    API request and JSON-schema output.
    """

    name = "bedrock"
    supports_server_fallbacks = False  # server-side fallbacks are a Claude API feature

    def _create_client(self) -> Any:
        region = os.environ.get("AWS_REGION") or os.environ.get("AWS_DEFAULT_REGION")
        if not region:
            raise ProviderCallError(self.name, "AWS_REGION is not set")
        return AsyncAnthropicBedrock(aws_region=region)

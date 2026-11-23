"""The LLM Gateway (CPS-02): the only route from application code to a model.

Every call is a named, versioned prompt plus a Pydantic output model. The
gateway picks provider and model from config, validates the output, retries
once with the validation error, and logs the call without document text.
"""

from __future__ import annotations

import json
import logging
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Generic, TypeVar

from pydantic import BaseModel, ValidationError

from app.llm.config import ConfigError, LLMConfig, TaskConfig, load_llm_config
from app.llm.prompts import PromptError, load_prompt
from app.llm.types import (
    AdapterRequest,
    AdapterResponse,
    Message,
    ProviderAdapter,
    ProviderCallError,
)

T = TypeVar("T", bound=BaseModel)

call_log = logging.getLogger("app.llm.calls")

MAX_ATTEMPTS = 2  # the first call plus one retry on schema failure

RETRY_INSTRUCTION = (
    "Your previous reply did not match the required output schema.\n"
    "Validation error:\n{error}\n"
    "Reply again with only output that matches the schema exactly."
)


class GatewayError(Exception):
    """A gateway call could not produce a valid output."""

    def __init__(self, task: str, prompt_id: str, reason: str) -> None:
        super().__init__(f"[{task} / {prompt_id}] {reason}")
        self.task = task
        self.prompt_id = prompt_id
        self.reason = reason


@dataclass(frozen=True)
class GatewayResult(Generic[T]):
    output: T
    task: str
    prompt_id: str
    provider: str
    model: str
    input_tokens: int
    output_tokens: int
    latency_ms: int
    attempts: int


def _validation_message(exc: ValidationError) -> str:
    # Field locations and error types only: never echo the input values back.
    lines = [
        f"- {'.'.join(str(p) for p in err['loc']) or '<root>'}: {err['msg']}"
        for err in exc.errors(include_input=False, include_url=False)
    ]
    return "\n".join(lines)


class Gateway:
    def __init__(
        self,
        adapters: Mapping[str, ProviderAdapter],
        config: LLMConfig | Callable[[], LLMConfig],
        prompts_dir: Path | None = None,
    ) -> None:
        self._adapters = dict(adapters)
        self._config = config
        self._prompts_dir = prompts_dir

    @property
    def config(self) -> LLMConfig:
        return self._config() if callable(self._config) else self._config

    def _task_config(self, task: str, provider: str | None) -> TaskConfig:
        return self.config.for_task(task, provider)

    def _log(self, **fields: Any) -> None:
        call_log.info(json.dumps(fields, sort_keys=True), extra={"llm_call": fields})

    async def run(
        self,
        task: str,
        prompt_id: str,
        variables: dict[str, Any],
        output_model: type[T],
        *,
        provider: str | None = None,
    ) -> GatewayResult[T]:
        """Run one call. ``provider`` overrides the configured provider (smoke, evaluation)."""
        try:
            rendered = load_prompt(prompt_id, self._prompts_dir).render(variables)
        except PromptError as exc:
            raise GatewayError(task, prompt_id, str(exc)) from exc

        try:
            settings = self._task_config(task, provider)
        except ConfigError as exc:
            raise GatewayError(task, prompt_id, str(exc)) from exc
        adapter = self._adapters.get(settings.provider)
        if adapter is None:
            raise GatewayError(task, prompt_id, f"no adapter for provider '{settings.provider}'")

        messages = [Message("user", rendered.user)]
        total_in = total_out = 0
        started = time.perf_counter()
        last_error = "no attempt made"

        for attempt in range(1, MAX_ATTEMPTS + 1):
            request = AdapterRequest(
                model=settings.model,
                system=rendered.system,
                messages=list(messages),
                output_model=output_model,
                max_tokens=settings.max_tokens,
                temperature=settings.temperature,
                options=dict(settings.options),
            )
            call_started = time.perf_counter()
            log_fields: dict[str, Any] = {
                "task": task,
                "prompt_id": prompt_id,
                "provider": settings.provider,
                "model": settings.model,
                "attempt": attempt,
            }
            try:
                response: AdapterResponse = await adapter.complete(request)
            except ProviderCallError as exc:
                self._log(
                    **log_fields,
                    input_tokens=0,
                    output_tokens=0,
                    latency_ms=round((time.perf_counter() - call_started) * 1000),
                    success=False,
                    error="provider_error",
                )
                raise GatewayError(task, prompt_id, f"provider call failed: {exc.reason}") from exc

            total_in += response.input_tokens
            total_out += response.output_tokens
            log_fields.update(
                input_tokens=response.input_tokens,
                output_tokens=response.output_tokens,
                latency_ms=round((time.perf_counter() - call_started) * 1000),
            )

            if response.refused:
                self._log(**log_fields, success=False, error="refused")
                raise GatewayError(task, prompt_id, "the model declined the request")

            try:
                output = output_model.model_validate_json(response.text)
            except ValidationError as exc:
                last_error = _validation_message(exc)
                if response.truncated:
                    last_error = f"output truncated at max_tokens\n{last_error}"
                self._log(**log_fields, success=False, error="schema_validation")
                if response.text:
                    messages.append(Message("assistant", response.text))
                messages.append(Message("user", RETRY_INSTRUCTION.format(error=last_error)))
                continue

            self._log(**log_fields, success=True)
            return GatewayResult(
                output=output,
                task=task,
                prompt_id=prompt_id,
                provider=settings.provider,
                model=settings.model,
                input_tokens=total_in,
                output_tokens=total_out,
                latency_ms=round((time.perf_counter() - started) * 1000),
                attempts=attempt,
            )

        raise GatewayError(
            task,
            prompt_id,
            f"output failed schema validation after {MAX_ATTEMPTS} attempts:\n{last_error}",
        )


_default_gateway: Gateway | None = None


def default_adapters() -> dict[str, ProviderAdapter]:
    # Adapters create their clients on first use, so a missing key for one
    # provider never blocks the others.
    from app.llm.adapters.anthropic import AnthropicAdapter, BedrockClaudeAdapter
    from app.llm.adapters.langchain import gemini_adapter, openai_adapter

    return {
        "anthropic": AnthropicAdapter(),
        "bedrock": BedrockClaudeAdapter(),
        "gemini": gemini_adapter(),
        "openai": openai_adapter(),
    }


def get_gateway() -> Gateway:
    global _default_gateway
    if _default_gateway is None:
        _default_gateway = Gateway(default_adapters(), load_llm_config)
    return _default_gateway


async def run(
    task: str,
    prompt_id: str,
    variables: dict[str, Any],
    output_model: type[T],
    *,
    provider: str | None = None,
) -> GatewayResult[T]:
    """Run one structured-output call through the default gateway."""
    return await get_gateway().run(task, prompt_id, variables, output_model, provider=provider)

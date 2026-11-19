"""Per-task provider and model selection, loaded from backend/config/llm.yaml.

Resolution for a task, most specific first:
  1. the provider override passed by the caller (smoke tests, evaluation)
  2. the task's own settings in ``tasks``
  3. that provider's defaults in ``providers``
  4. the top-level defaults
A task's ``model`` applies only while the task runs on its own provider; with
another provider the call uses that provider's default model.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field

DEFAULT_CONFIG_PATH = Path(__file__).resolve().parents[2] / "config" / "llm.yaml"


class ConfigError(Exception):
    """llm.yaml names a provider or task setting that cannot be resolved."""


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ProviderDefaults(_Strict):
    model: str
    # None means "do not send": some models reject sampling parameters.
    temperature: float | None = 0.0
    options: dict[str, Any] = Field(default_factory=dict)


class TaskOverride(_Strict):
    provider: str | None = None
    model: str | None = None
    temperature: float | None = None
    max_tokens: int | None = Field(default=None, gt=0)
    options: dict[str, Any] = Field(default_factory=dict)


class TaskConfig(_Strict):
    """Fully resolved settings for one call."""

    provider: str
    model: str
    temperature: float | None
    max_tokens: int = Field(gt=0)
    options: dict[str, Any] = Field(default_factory=dict)


class EmbeddingConfig(_Strict):
    provider: str
    model: str
    # Expected vector length. Vectors from two models never share an index.
    dimensions: int | None = Field(default=None, gt=0)


class LLMConfig(_Strict):
    version: str
    label: Literal["illustrative", "authoritative"]
    default_provider: str
    max_tokens: int = Field(default=16000, gt=0)
    providers: dict[str, ProviderDefaults]
    tasks: dict[str, TaskOverride] = Field(default_factory=dict)
    embeddings: EmbeddingConfig | None = None

    def for_task(self, task: str, provider: str | None = None) -> TaskConfig:
        override = self.tasks.get(task, TaskOverride())
        task_provider = override.provider or self.default_provider
        chosen = provider or task_provider
        defaults = self.providers.get(chosen)
        if defaults is None:
            raise ConfigError(f"provider '{chosen}' is not configured in llm.yaml")

        on_own_provider = chosen == task_provider
        model = override.model if (override.model and on_own_provider) else defaults.model
        temperature = (
            override.temperature
            if "temperature" in override.model_fields_set
            else defaults.temperature
        )
        return TaskConfig(
            provider=chosen,
            model=model,
            temperature=temperature,
            max_tokens=override.max_tokens or self.max_tokens,
            # Adapters read only the option names they know, so options meant
            # for one provider are harmless when the task runs on another.
            options={**defaults.options, **override.options},
        )


def load_llm_config(path: Path | None = None) -> LLMConfig:
    env_path = os.environ.get("LLM_CONFIG_PATH")
    config_path = path or (Path(env_path) if env_path else DEFAULT_CONFIG_PATH)
    with config_path.open(encoding="utf-8") as fh:
        raw = yaml.safe_load(fh)
    return LLMConfig.model_validate(raw)

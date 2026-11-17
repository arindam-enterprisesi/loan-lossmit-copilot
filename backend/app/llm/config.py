"""Per-task provider and model selection, loaded from backend/config/llm.yaml."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field

DEFAULT_CONFIG_PATH = Path(__file__).resolve().parents[2] / "config" / "llm.yaml"


class TaskConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider: str
    model: str
    temperature: float = 0.0
    max_tokens: int = Field(default=16000, gt=0)
    # Provider-specific settings passed through to the adapter (e.g. effort, fallbacks).
    options: dict[str, Any] = Field(default_factory=dict)


class LLMConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: str
    label: Literal["illustrative", "authoritative"]
    defaults: TaskConfig
    tasks: dict[str, dict[str, Any]] = Field(default_factory=dict)

    def for_task(self, task: str) -> TaskConfig:
        """Task settings, falling back field by field to ``defaults``.

        ``task`` may be dotted (``agents.writer``); an unknown task uses the defaults.
        """
        override = self.tasks.get(task, {})
        merged = self.defaults.model_dump()
        options = {**merged["options"], **override.get("options", {})}
        merged.update({k: v for k, v in override.items() if k != "options"})
        merged["options"] = options
        return TaskConfig.model_validate(merged)


def load_llm_config(path: Path | None = None) -> LLMConfig:
    env_path = os.environ.get("LLM_CONFIG_PATH")
    config_path = path or (Path(env_path) if env_path else DEFAULT_CONFIG_PATH)
    with config_path.open(encoding="utf-8") as fh:
        raw = yaml.safe_load(fh)
    return LLMConfig.model_validate(raw)

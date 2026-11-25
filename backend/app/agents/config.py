"""``config/agents.yaml``: review priorities and blocked words for the agents (rule 4)."""

from __future__ import annotations

from fnmatch import fnmatchcase
from functools import lru_cache
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field

from app.db.enums import ReviewPriority

CONFIG_PATH = Path(__file__).resolve().parents[2] / "config" / "agents.yaml"


class PriorityRule(BaseModel):
    model_config = ConfigDict(extra="forbid")

    pattern: str
    priority: ReviewPriority


class ResearchQuestion(BaseModel):
    model_config = ConfigDict(extra="forbid")

    pattern: str
    question: str


class AgentsConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: str
    label: Literal["illustrative", "authoritative"]
    source: str
    priority_by_code: list[PriorityRule] = Field(min_length=1)
    skip_codes: list[str]
    extra_blocked_words: list[str]
    research_questions: list[ResearchQuestion]
    researcher_concurrency: int = Field(ge=1, le=16)

    def priority(self, code: str) -> ReviewPriority:
        for rule in self.priority_by_code:
            if fnmatchcase(code, rule.pattern):
                return rule.priority
        return ReviewPriority.INFORMATION

    def research_question(self, topic: str) -> str | None:
        for rule in self.research_questions:
            if fnmatchcase(topic, rule.pattern):
                return rule.question
        return None


def load_agents_config(path: Path = CONFIG_PATH) -> AgentsConfig:
    return AgentsConfig.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))


@lru_cache
def get_agents_config() -> AgentsConfig:
    return load_agents_config()

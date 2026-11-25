"""``config/rag.yaml``: the guideline assistant's settings, versioned and labelled (rule 4)."""

from __future__ import annotations

from decimal import Decimal
from functools import lru_cache
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field

CONFIG_PATH = Path(__file__).resolve().parents[2] / "config" / "rag.yaml"


class RagConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: str
    label: Literal["illustrative", "authoritative"]
    source: str
    retrieval: Literal["lexical"]
    top_k: int = Field(ge=1, le=20)
    min_coverage: Decimal = Field(ge=0, le=1)
    max_quote_chars: int = Field(ge=20)
    bm25_k1: Decimal
    bm25_b: Decimal
    regulation_notice: str


def load_rag_config(path: Path = CONFIG_PATH) -> RagConfig:
    return RagConfig.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))


@lru_cache
def get_rag_config() -> RagConfig:
    return load_rag_config()

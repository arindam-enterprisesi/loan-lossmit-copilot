"""Upload and ingestion settings from backend/config/ingestion.yaml (versioned, labelled)."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field

DEFAULT_INGESTION_CONFIG_PATH = Path(__file__).resolve().parents[2] / "config" / "ingestion.yaml"
BYTES_PER_MIB = 1024 * 1024


class IngestionConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: str
    label: Literal["illustrative", "authoritative"]
    max_file_mb: int = Field(gt=0)
    render_dpi: int = Field(gt=0)

    @property
    def max_file_bytes(self) -> int:
        return self.max_file_mb * BYTES_PER_MIB


def load_ingestion_config(path: Path | None = None) -> IngestionConfig:
    with (path or DEFAULT_INGESTION_CONFIG_PATH).open(encoding="utf-8") as fh:
        return IngestionConfig.model_validate(yaml.safe_load(fh))


@lru_cache
def get_ingestion_config() -> IngestionConfig:
    return load_ingestion_config()

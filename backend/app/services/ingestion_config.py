"""Upload and ingestion settings from backend/config/ingestion.yaml (versioned, labelled)."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator

DEFAULT_INGESTION_CONFIG_PATH = Path(__file__).resolve().parents[2] / "config" / "ingestion.yaml"
BYTES_PER_MIB = 1024 * 1024


class OcrSettings(BaseModel):
    """How a page image is prepared for, and read by, Tesseract."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    min_text_chars: int = Field(ge=1)
    target_dpi: int = Field(gt=0)
    max_skew_degrees: float = Field(ge=0, le=45)
    denoise_kernel: int = Field(ge=1)
    threshold_block_size: int = Field(ge=3)
    threshold_c: int
    language: str = Field(min_length=1)
    tesseract_config: str

    @field_validator("denoise_kernel", "threshold_block_size")
    @classmethod
    def _odd(cls, value: int) -> int:
        # OpenCV's median blur and adaptive threshold both need an odd window.
        if value % 2 == 0:
            raise ValueError("must be an odd number of pixels")
        return value


class IngestionConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: str
    label: Literal["illustrative", "authoritative"]
    max_file_mb: int = Field(gt=0)
    render_dpi: int = Field(gt=0)
    ocr: OcrSettings

    @property
    def max_file_bytes(self) -> int:
        return self.max_file_mb * BYTES_PER_MIB

    @property
    def ocr_scale(self) -> float:
        """How much to enlarge a page image before OCR: target dpi over the dpi it was drawn at."""
        return self.ocr.target_dpi / self.render_dpi


def load_ingestion_config(path: Path | None = None) -> IngestionConfig:
    with (path or DEFAULT_INGESTION_CONFIG_PATH).open(encoding="utf-8") as fh:
        return IngestionConfig.model_validate(yaml.safe_load(fh))


@lru_cache
def get_ingestion_config() -> IngestionConfig:
    return load_ingestion_config()

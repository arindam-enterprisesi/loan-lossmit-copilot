"""Login settings from backend/config/auth.yaml (versioned, labelled illustrative/authoritative)."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field

DEFAULT_AUTH_CONFIG_PATH = Path(__file__).resolve().parents[2] / "config" / "auth.yaml"


class AuthConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: str
    label: Literal["illustrative", "authoritative"]
    access_token_minutes: int = Field(gt=0)


def load_auth_config(path: Path | None = None) -> AuthConfig:
    with (path or DEFAULT_AUTH_CONFIG_PATH).open(encoding="utf-8") as fh:
        return AuthConfig.model_validate(yaml.safe_load(fh))


@lru_cache
def get_auth_config() -> AuthConfig:
    return load_auth_config()

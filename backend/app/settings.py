"""Application settings, read from the environment and the repo-root ``.env``.

LLM provider keys (ANTHROPIC_API_KEY and friends) are read by their SDKs inside
``app.llm``, so unknown variables are ignored here.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=REPO_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # AWS: either AWS_PROFILE or the key pair; with neither, boto3's default chain applies.
    aws_region: str | None = None
    aws_profile: str | None = None
    aws_access_key_id: SecretStr | None = None
    aws_secret_access_key: SecretStr | None = None
    aws_session_token: SecretStr | None = None

    s3_bucket: str = ""
    # One prefix per developer (for example ``dev/abhay/``) and one for the demo.
    s3_prefix: str = "dev/local/"

    database_url: str = "postgresql+asyncpg://copilot:copilot@localhost:5432/copilot"
    redis_url: str = "redis://localhost:6379/0"

    # Which reader the document pipeline uses for classify and extract. "auto" uses the real LLM
    # task when app.llm provides it and the rule-based fake when it does not (per task, and the
    # worker logs which); "fake" forces the fake (offline development, tests).
    pipeline_llm: Literal["auto", "fake"] = "auto"

    # arq job limits. One job reads every document of an upload and a real model call can take
    # minutes (Gemini classify took 75 to 142 s each when tested), so arq's default timeout of
    # 300 s would cut a job off part way. Seconds, and how many jobs one worker runs at once.
    worker_job_timeout: int = Field(default=1800, gt=0)
    worker_max_jobs: int = Field(default=4, gt=0)

    jwt_secret: SecretStr = SecretStr("change-me")
    # Password for the three seeded demo logins (synthetic demo only).
    demo_password: SecretStr = SecretStr("demo")

    @field_validator("aws_profile", "aws_region", mode="before")
    @classmethod
    def _blank_is_unset(cls, value: object) -> object:
        # `AWS_PROFILE=` copied from .env.example arrives as "", which boto3 would treat as a
        # profile named "". A blank value means "not set".
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @field_validator("s3_prefix")
    @classmethod
    def _normalise_prefix(cls, value: str) -> str:
        value = value.strip().lstrip("/")
        return value if value.endswith("/") or not value else f"{value}/"


@lru_cache
def get_settings() -> Settings:
    return Settings()

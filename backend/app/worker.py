"""arq background worker. Real jobs (OCR, extraction, analysis) land from D3."""

from __future__ import annotations

from typing import Any, ClassVar

from arq.connections import RedisSettings

from app.settings import get_settings


async def ping(ctx: dict[str, Any]) -> str:
    return "pong"


class WorkerSettings:
    functions: ClassVar[list[Any]] = [ping]
    redis_settings = RedisSettings.from_dsn(get_settings().redis_url)

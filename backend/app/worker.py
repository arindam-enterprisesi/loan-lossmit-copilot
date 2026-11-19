"""arq background worker. Document ingestion runs here; OCR-dependent and later jobs land from D3.

``ctx`` normally holds nothing of ours; tests put a ``storage``, ``ocr``, ``session_factory``
or ``ingestion_config`` in it to run a job against fakes.
"""

from __future__ import annotations

import uuid
from typing import Any, ClassVar

from arq.connections import RedisSettings

from app.db.session import get_sessionmaker
from app.services.ingestion import NotImplementedOcr, run_ingest_job
from app.services.ingestion_config import get_ingestion_config
from app.settings import get_settings
from app.storage import Storage


async def ping(ctx: dict[str, Any]) -> str:
    return "pong"


async def ingest_documents(ctx: dict[str, Any], job_id: str, document_ids: list[str]) -> None:
    """Read uploaded documents into pages and numbered lines (``app.services.ingestion``)."""
    config = ctx.get("ingestion_config") or get_ingestion_config()
    await run_ingest_job(
        ctx.get("session_factory") or get_sessionmaker(),
        ctx.get("storage") or Storage(),
        ctx.get("ocr") or NotImplementedOcr(),
        uuid.UUID(job_id),
        [uuid.UUID(d) for d in document_ids],
        dpi=config.render_dpi,
    )


class WorkerSettings:
    functions: ClassVar[list[Any]] = [ping, ingest_documents]
    redis_settings = RedisSettings.from_dsn(get_settings().redis_url)

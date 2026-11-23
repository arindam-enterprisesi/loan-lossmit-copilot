"""arq background worker. It runs the document pipeline (``app.services.pipeline``).

``ctx`` normally holds nothing of ours; tests put a ``storage``, ``ocr``, ``classifier``,
``extractor``, ``session_factory`` or ``ingestion_config`` in it to run a job against fakes.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any, ClassVar

from arq.connections import RedisSettings

from app.db.session import get_sessionmaker
from app.services.classification import get_classifier
from app.services.document_config import get_document_fields, get_validation_config
from app.services.extractor import get_extractor
from app.services.income_runs import run_income_job
from app.services.ingestion import NotImplementedOcr
from app.services.ingestion_config import get_ingestion_config
from app.services.pipeline import Readers, run_pipeline_job
from app.settings import get_settings
from app.storage import Storage, drop_blank_aws_env

logger = logging.getLogger(__name__)


async def startup(ctx: dict[str, Any]) -> None:
    # `AWS_PROFILE=` copied from .env.example is blank, which the AWS SDK reads as a profile named
    # "". Remove blank AWS_* variables before any client (S3, or Bedrock in app.llm) is created.
    drop_blank_aws_env()
    logger.info("worker started (PIPELINE_LLM=%s)", get_settings().pipeline_llm)


async def ping(ctx: dict[str, Any]) -> str:
    return "pong"


async def process_documents(
    ctx: dict[str, Any],
    job_id: str,
    document_ids: list[str],
    stages: list[str] | None = None,
    force_extract: bool = False,
) -> None:
    """Take uploaded documents through ingest, classify, extract, validate and ready."""
    config = ctx.get("ingestion_config") or get_ingestion_config()
    readers = Readers(
        storage=ctx.get("storage") or Storage(),
        ocr=ctx.get("ocr") or NotImplementedOcr(),
        classifier=ctx.get("classifier") or get_classifier(),
        extractor=ctx.get("extractor") or get_extractor(),
        dpi=config.render_dpi,
        rules=get_validation_config(),
        cfg=get_document_fields(),
    )
    await run_pipeline_job(
        ctx.get("session_factory") or get_sessionmaker(),
        readers,
        uuid.UUID(job_id),
        [uuid.UUID(d) for d in document_ids],
        stages=stages,
        force_extract=force_extract,
    )


async def run_income_analysis(ctx: dict[str, Any], job_id: str, run_id: str) -> None:
    """Analyse a case's documents for income and store the result (plain code, no model)."""
    await run_income_job(
        ctx.get("session_factory") or get_sessionmaker(), uuid.UUID(job_id), uuid.UUID(run_id)
    )


class WorkerSettings:
    functions: ClassVar[list[Any]] = [ping, process_documents, run_income_analysis]
    on_startup = startup
    redis_settings = RedisSettings.from_dsn(get_settings().redis_url)
    job_timeout = get_settings().worker_job_timeout
    max_jobs = get_settings().worker_max_jobs

"""arq background worker. It runs the document pipeline (``app.services.pipeline``).

``ctx`` normally holds nothing of ours; tests put a ``storage``, ``ocr``, ``classifier``,
``extractor``, ``session_factory`` or ``ingestion_config`` in it to run a job against fakes.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any, ClassVar

from arq.connections import RedisSettings

from app.agents.jobs import run_agents_job
from app.db.session import get_sessionmaker
from app.services.asset_runs import run_asset_job
from app.services.classification import get_classifier
from app.services.credit_runs import run_credit_job
from app.services.document_config import get_document_fields, get_validation_config
from app.services.extractor import get_extractor
from app.services.hardship import run_hardship_job
from app.services.income_runs import run_income_job
from app.services.ingestion_config import get_ingestion_config
from app.services.ocr import default_ocr
from app.services.pipeline import Readers, run_pipeline_job
from app.services.recommendation_runs import run_recommendation_job
from app.settings import get_settings
from app.storage import Storage, drop_blank_aws_env

logger = logging.getLogger(__name__)


async def startup(ctx: dict[str, Any]) -> None:
    # `AWS_PROFILE=` copied from .env.example is blank, which the AWS SDK reads as a profile named
    # "". Remove blank AWS_* variables before any client (S3, or Bedrock in app.llm) is created.
    drop_blank_aws_env()
    settings = get_settings()
    logger.info(
        "worker started (PIPELINE_LLM=%s, OCR_ENGINE=%s)",
        settings.pipeline_llm,
        settings.ocr_engine,
    )


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
        ocr=ctx.get("ocr") or default_ocr(config, get_settings().ocr_engine),
        classifier=ctx.get("classifier") or get_classifier(),
        extractor=ctx.get("extractor") or get_extractor(),
        dpi=config.render_dpi,
        rules=get_validation_config(),
        cfg=get_document_fields(),
        min_text_chars=config.ocr.min_text_chars,
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


async def run_asset_analysis(ctx: dict[str, Any], job_id: str, run_id: str) -> None:
    """Label a case's statement lines, analyse assets and liabilities, store the result."""
    await run_asset_job(
        ctx.get("session_factory") or get_sessionmaker(),
        uuid.UUID(job_id),
        uuid.UUID(run_id),
        labeller=ctx.get("labeller"),
    )


async def run_hardship_reading(ctx: dict[str, Any], job_id: str, user_id: str) -> None:
    """Read a case's hardship letter, store the profile, and build the budget."""
    await run_hardship_job(
        ctx.get("session_factory") or get_sessionmaker(),
        uuid.UUID(job_id),
        uuid.UUID(user_id),
        reader=ctx.get("hardship_reader"),
        labeller=ctx.get("labeller"),
    )


async def run_credit_analysis(ctx: dict[str, Any], job_id: str, run_id: str) -> None:
    """Analyse a case's credit report and store the result (plain code, no model)."""
    await run_credit_job(
        ctx.get("session_factory") or get_sessionmaker(), uuid.UUID(job_id), uuid.UUID(run_id)
    )


async def run_recommendation_rules(ctx: dict[str, Any], job_id: str, user_id: str) -> None:
    """Apply the investor's rule set to a case and store the waterfall and lender view."""
    await run_recommendation_job(
        ctx.get("session_factory") or get_sessionmaker(),
        uuid.UUID(job_id),
        uuid.UUID(user_id),
        rule_set=ctx.get("rule_set"),
    )


async def run_agents(
    ctx: dict[str, Any], job_id: str, user_id: str, kind: str, agent: str | None
) -> None:
    """Run the underwriting or LM agents (or one of them again) and write the next report."""
    await run_agents_job(
        ctx.get("session_factory") or get_sessionmaker(),
        uuid.UUID(job_id),
        uuid.UUID(user_id) if user_id else None,
        "lm" if kind == "lm" else "underwriting",
        agent,
    )


class WorkerSettings:
    functions: ClassVar[list[Any]] = [
        ping,
        process_documents,
        run_income_analysis,
        run_asset_analysis,
        run_hardship_reading,
        run_recommendation_rules,
        run_credit_analysis,
        run_agents,
    ]
    on_startup = startup
    redis_settings = RedisSettings.from_dsn(get_settings().redis_url)
    job_timeout = get_settings().worker_job_timeout
    max_jobs = get_settings().worker_max_jobs

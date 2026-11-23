"""Seed Angela Whitfield's hardship profile (Feature Design 7.8) without calling a model.

The v0.5 demo shows her letter read into a profile: reason, onset, duration and intent, each with
its quote highlighted on its line. Until a model provider works, the reading is a data file (the
worked example in Arindam's ``tests/llm/test_hardship.py``). Code still checks every quote against
the letter's lines, so what the screen shows as verified is verified. The run is labelled
``seeded_sample`` so nobody mistakes it for a model's reading.
"""

from __future__ import annotations

import json
import logging
import uuid
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.enums import HardshipSource
from app.db.models import HardshipProfile
from app.llm.checks import verify_quotes
from app.llm.samples import load_lines
from app.prompts.schemas.hardship import HardshipConfig, hardship_profile_model
from app.prompts.schemas.hardship import HardshipProfile as ReadProfile
from app.services import hardship_runs

logger = logging.getLogger(__name__)

SEED_FILE = Path(__file__).with_name("angela_hardship_profile.json")
SAMPLE_LETTER = "angela_hardship_letter"  # app/llm/samples, made from the generated letter


def load_seed_profile(config: HardshipConfig) -> ReadProfile:
    """The seeded reading as the profile model for the configured categories."""
    data = json.loads(SEED_FILE.read_text(encoding="utf-8"))["profile"]
    return hardship_profile_model(config.keys).model_validate(data)


async def seed_hardship_profile(session: AsyncSession, case_id: uuid.UUID) -> HardshipProfile:
    """Store the seeded profile for the case, unless it already has one. The caller commits.

    The quotes are checked against the case's uploaded hardship letter when there is one (and the
    profile then names that document, so the screen can highlight the lines); otherwise against the
    sample lines the letter was made from, and no document is named.
    """
    existing = await hardship_runs.seeded_profile(session, case_id)
    if existing is not None:
        return existing

    config = hardship_runs.get_hardship_config()
    letter = await hardship_runs.load_letter(session, case_id)
    lines = letter.lines if letter else load_lines(SAMPLE_LETTER)
    logger.info(
        "hardship seed checked against %s", "the uploaded letter" if letter else "sample lines"
    )
    profile = load_seed_profile(config)
    return await hardship_runs.store_profile(
        session,
        case_id=case_id,
        document_id=letter.document_id if letter else None,
        profile=profile,
        checks=verify_quotes(profile, lines, max_quote_chars=config.max_quote_chars),
        config=config,
        source=HardshipSource.SEEDED_SAMPLE,
        created_by=None,
    )

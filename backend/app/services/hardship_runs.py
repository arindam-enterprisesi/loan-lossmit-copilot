"""Hardship assessments: store a profile read from a letter, find the latest, read it back.

A hardship letter is read into a profile (reason, onset, duration, intent, timeline, enclosed
documents; Feature Design 7.5). Each item keeps its quote and the line IDs it came from, and code
checks the quote against those lines (``app.llm.checks.verify_quotes``). The profile is what the
borrower says. It is stored as an ``analysis_runs`` row (feature ``hardship``) with one
``hardship_profiles`` row, so "latest" means the newest run, like every other analysis. A quote that
fails its check also raises a flag, so it shows with the other flags of the case.

This module is the database side and has no model call: the reading comes from the caller (the demo
seed today; the service that runs ``read_hardship_letter`` later). Nothing is overwritten (rule 6):
a new reading is a new run, and earlier ones stay as history.
"""

from __future__ import annotations

import hashlib
import logging
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from functools import lru_cache
from typing import Any

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.enums import AnalysisFeature, AnalysisStatus, HardshipSource
from app.db.models import AnalysisRun, Document, Flag, HardshipProfile, Line
from app.llm.checks import QUOTE_TOO_LONG, UNVERIFIED_QUOTE, QuoteCheck
from app.llm.tasks import DocumentLine
from app.prompts.schemas.hardship import (
    DEFAULT_HARDSHIP_CONFIG_PATH,
    HardshipConfig,
    load_hardship_config,
)
from app.prompts.schemas.hardship import HardshipProfile as ReadProfile
from app.services import audit
from app.services import flags as flag_service
from app.services.doc_lines import doc_lines, parse_ref

logger = logging.getLogger(__name__)

FEATURE = "hardship"
LETTER_TYPE = "hardship_letter"
# Profile parts that hold one item, and parts that hold a list of them.
SINGLE_ITEMS = ("primary_reason", "onset", "duration", "intent")
LIST_ITEMS = ("other_reasons", "timeline", "enclosed_documents")
LABELS = {
    "primary_reason": "Primary reason",
    "other_reasons": "Other reason",
    "onset": "Onset",
    "duration": "Duration",
    "intent": "Intent",
    "timeline": "Timeline event",
    "enclosed_documents": "Enclosed document",
}
# Fixed wording for each way a quote can fail its check (no decision words, rule 3).
FAILURE_TEXT = {
    UNVERIFIED_QUOTE: "we couldn't find this quote in the lines it cites.",
    QUOTE_TOO_LONG: "this quote is longer than a short quote should be.",
}


@lru_cache
def get_hardship_config() -> HardshipConfig:
    return load_hardship_config()


def config_snapshot(config: HardshipConfig) -> dict[str, dict[str, str]]:
    """``analysis_runs.config_versions`` for a hardship run: which settings the reading used."""
    digest = hashlib.sha256(DEFAULT_HARDSHIP_CONFIG_PATH.read_bytes()).hexdigest()
    return {
        FEATURE: {
            "name": FEATURE,
            "version": config.version,
            "label": config.label,
            "hash": digest,
        }
    }


# --- the letter -----------------------------------------------------------------------------


@dataclass(frozen=True)
class Letter:
    """A case's hardship letter as ingestion stored it: its document and numbered lines."""

    document_id: uuid.UUID
    lines: list[DocumentLine]


async def load_letter(session: AsyncSession, case_id: uuid.UUID) -> Letter | None:
    """The newest hardship letter of the case that has been read into lines, if any."""
    document = await session.scalar(
        sa.select(Document)
        .where(Document.case_id == case_id, Document.doc_type == LETTER_TYPE)
        .order_by(Document.created_at.desc(), Document.id.desc())
        .limit(1)
    )
    if document is None:
        return None
    rows = (
        await session.execute(
            sa.select(Line.line_ref, Line.text).where(Line.document_id == document.id)
        )
    ).all()
    lines = [
        DocumentLine(ln.page, ln.line, ln.text) for ln in doc_lines((r[0], r[1]) for r in rows)
    ]
    return Letter(document.id, lines) if lines else None


# --- storing a reading ----------------------------------------------------------------------


def _verdict(check: QuoteCheck | None) -> dict[str, Any]:
    """What code found when it checked an item's quote, kept beside the item (rule 2)."""
    return {
        "verified": check.verified if check else True,
        "check_flags": check.flags if check else [],
    }


def _annotate(data: dict[str, Any], checks: dict[str, QuoteCheck]) -> dict[str, Any]:
    """The profile as plain data with each item's ``verified`` and ``check_flags`` added."""
    out: dict[str, Any] = {}
    for name in SINGLE_ITEMS:
        out[name] = {**data[name], **_verdict(checks.get(name))}
    for name in LIST_ITEMS:
        out[name] = [
            {**item, **_verdict(checks.get(f"{name}[{index}]"))}
            for index, item in enumerate(data[name])
        ]
    return out


def _label(path: str) -> str:
    """``"timeline[1]"`` -> ``"Timeline event 2"``; ``"intent"`` -> ``"Intent"``."""
    name, _, rest = path.partition("[")
    label = LABELS.get(name, name)
    return f"{label} {int(rest.rstrip(']')) + 1}" if rest else label


def _evidence(
    run_id: uuid.UUID, path: str, document_id: uuid.UUID | None, lines: Sequence[str]
) -> dict[str, Any]:
    """Where the quote was said to be: the letter and the cited lines of its first page."""
    evidence: dict[str, Any] = {"run_id": str(run_id), "path": path}
    refs = [(parse_ref(ref), ref) for ref in lines]
    if document_id is not None and refs and all(parsed for parsed, _ in refs):
        first_page = next(parsed[0] for parsed, _ in refs if parsed)
        evidence |= {
            "document_id": str(document_id),
            "page": first_page,
            "line_ids": [ref for parsed, ref in refs if parsed and parsed[0] == first_page],
        }
    return evidence


async def store_profile(
    session: AsyncSession,
    *,
    case_id: uuid.UUID,
    document_id: uuid.UUID | None,
    profile: ReadProfile,
    checks: Sequence[QuoteCheck],
    config: HardshipConfig,
    source: HardshipSource,
    created_by: uuid.UUID | None,
) -> HardshipProfile:
    """Store a reading as a new run. Flushes; the caller commits.

    ``checks`` are the quote checks of the profile (``verify_quotes``); each failed one also raises
    a flag whose evidence points at the lines it cited.
    """
    now = datetime.now(UTC)  # set here, not by now(): runs made in one transaction must still order
    run = AnalysisRun(
        case_id=case_id,
        feature=AnalysisFeature.HARDSHIP,
        status=AnalysisStatus.SUCCEEDED,
        started_at=now,
        finished_at=now,
        config_versions=config_snapshot(config),
        created_by=created_by,
    )
    session.add(run)
    await session.flush()

    by_path = {check.path: check for check in checks}
    parts = _annotate(profile.model_dump(), by_path)
    row = HardshipProfile(
        run_id=run.id,
        case_id=case_id,
        document_id=document_id,
        primary_reason=parts["primary_reason"],
        reasons=parts["other_reasons"],
        onset=parts["onset"],
        duration=parts["duration"],
        intent=parts["intent"],
        timeline=parts["timeline"],
        enclosed_documents=parts["enclosed_documents"],
        source=source,
    )
    session.add(row)
    await session.flush()

    for path, check in by_path.items():
        for code in check.flags:
            text = FAILURE_TEXT.get(code, f"the quote check reported {code}.")
            await flag_service.raise_flag(
                session,
                case_id=case_id,
                entity_type="hardship_item",
                entity_id=uuid.uuid5(run.id, f"{code}:{path}"),
                code=code,
                severity="warning",
                message=f"{_label(path)}: {text}",
                evidence=_evidence(run.id, path, document_id, check.lines),
                feature=FEATURE,
            )
    await audit.record(
        session,
        actor_id=created_by,
        role="system" if created_by is None else "user",
        action="hardship.profile_stored",
        entity_type="analysis_run",
        entity_id=run.id,
        case_id=case_id,
        after={
            "source": source.value,
            "quotes": len(by_path),
            "unverified_quotes": sum(1 for c in by_path.values() if not c.verified),
            "config_versions": run.config_versions,
        },
    )
    logger.info("hardship profile stored run=%s source=%s", run.id, source.value)
    return row


# --- reading it back ------------------------------------------------------------------------


@dataclass
class HardshipView:
    run: AnalysisRun
    profile: HardshipProfile
    flags: list[Flag]


async def latest(session: AsyncSession, case_id: uuid.UUID) -> HardshipView | None:
    """The newest hardship run of the case that has a profile, with its open flags."""
    found = (
        await session.execute(
            sa.select(AnalysisRun, HardshipProfile)
            .join(HardshipProfile, HardshipProfile.run_id == AnalysisRun.id)
            .where(AnalysisRun.case_id == case_id, AnalysisRun.feature == AnalysisFeature.HARDSHIP)
            .order_by(AnalysisRun.started_at.desc(), AnalysisRun.id.desc())
            .limit(1)
        )
    ).first()
    if found is None:
        return None
    run, profile = found
    flags = list(
        (
            await session.execute(
                sa.select(Flag)
                .where(Flag.feature == FEATURE, Flag.evidence["run_id"].astext == str(run.id))
                .order_by(Flag.code, Flag.message, Flag.id)
            )
        )
        .scalars()
        .all()
    )
    return HardshipView(run, profile, flags)


async def seeded_profile(session: AsyncSession, case_id: uuid.UUID) -> HardshipProfile | None:
    """The case's seeded sample profile, if it has one (the newest, should there be several)."""
    return await session.scalar(
        sa.select(HardshipProfile)
        .where(
            HardshipProfile.case_id == case_id,
            HardshipProfile.source == HardshipSource.SEEDED_SAMPLE,
        )
        .order_by(HardshipProfile.created_at.desc(), HardshipProfile.id.desc())
        .limit(1)
    )

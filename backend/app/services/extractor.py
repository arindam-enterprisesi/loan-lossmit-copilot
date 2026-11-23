"""The seam to the extract call: its result shape, the real adapter, and which one is used.

The shape is the one Feature Design 1.5 documents for the real call:
``{"fields": {name: {"value", "lines", "certainty"}}, "signals": [...]}``. ``LlmExtractor`` calls
Arindam's ``app.llm.tasks.extract`` and flattens its nested lists (earnings lines, transactions,
Box 12 entries) into the indexed field names the checks and the income analysis read
(``earnings_001_hours``). ``app.services.fake_reader.FakeExtractor`` is the rule-based stand-in for
offline work and tests; every extraction run records which one produced it.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol

from app.services.classification import PipelineUnavailableError, llm_tasks
from app.services.doc_lines import DocLine
from app.services.document_config import DocumentFieldsConfig, get_document_fields
from app.settings import get_settings

logger = logging.getLogger(__name__)

_ROW_PATH = re.compile(
    r"^(?P<source>[a-z][a-z0-9_]*)\[(?P<index>\d+)\]\.(?P<part>[a-z][a-z0-9_]*)$"
)


@dataclass(frozen=True)
class ExtractedField:
    value: str | None  # as printed, for example "2,083.61"
    lines: list[str]  # the line refs it came from
    certainty: str  # high | medium | low
    # "-" or "+" when the page prints an unsigned amount in a deposit or withdrawal column, so the
    # sign comes from the column heading. Applied to the normalised value only; the printed text
    # stays as read.
    sign: Literal["-", "+"] | None = None


@dataclass(frozen=True)
class ExtractionOutcome:
    fields: dict[str, ExtractedField]
    signals: list[str] = field(default_factory=list)
    provider: str = "fake"
    model: str = "rule-based-v1"
    prompt_id: str | None = None


class Extractor(Protocol):
    async def extract(self, doc_type: str, lines: Sequence[DocLine]) -> ExtractionOutcome: ...


# --- the real adapter -----------------------------------------------------------------------


def flatten_fields(
    doc_type: str, fields_model: Any, cfg: DocumentFieldsConfig, tasks: Any
) -> dict[str, ExtractedField]:
    """The extract schema's nested result as flat, named fields.

    Scalars keep their names (``cfg.rename`` maps the few that differ). A repeating group becomes
    ``<prefix><nnn>_<part>`` per row, numbered from 001 in document order, with the prefix from the
    type's ``rows`` config (``<list name>_`` when a list has none). Absent values (null) are left
    out: a required field the reader missed is added as an empty row later, so a person can type it.
    """
    flat: dict[str, ExtractedField] = {}
    headings: dict[
        tuple[str, int], str
    ] = {}  # (list, row) -> the deposit/withdrawal column heading
    amount_names: dict[tuple[str, int], str] = {}
    rows = {row.source: row for row in cfg.rows(doc_type)}

    for path, read in tasks.iter_extracted(fields_model):
        if read.value is None:
            continue
        mine = ExtractedField(read.value, list(read.lines), read.certainty)
        found = _ROW_PATH.match(path)
        if found is None:
            flat[cfg.rename(doc_type, path)] = mine
            continue
        source, index, part = found["source"], int(found["index"]), found["part"]
        row = rows.get(source)
        number = index + 1
        name = row.field_name(number, part) if row else f"{source}_{number:03d}_{part}"
        flat[name] = mine
        if row and row.sign_column == part:
            headings[(source, index)] = read.value
        if row and row.amount_part == part:
            amount_names[(source, index)] = name

    for key, heading in headings.items():
        sign = cfg.sign_for_column(doc_type, heading)
        amount_name = amount_names.get(key)
        if sign and amount_name and amount_name in flat:
            amount = flat[amount_name]
            flat[amount_name] = ExtractedField(amount.value, amount.lines, amount.certainty, sign)
    return flat


class LlmExtractor:
    """The real extract task (the only caller of it in the pipeline)."""

    def __init__(
        self,
        *,
        gateway: Any | None = None,
        provider: str | None = None,
        config: DocumentFieldsConfig | None = None,
    ) -> None:
        self._gateway = gateway
        self._provider = provider
        self._config = config

    async def extract(self, doc_type: str, lines: Sequence[DocLine]) -> ExtractionOutcome:
        tasks = llm_tasks()
        if tasks is None or not hasattr(tasks, "extract"):
            raise PipelineUnavailableError("app.llm.tasks.extract is not available")
        try:
            kind = tasks.DocumentType(doc_type)
        except ValueError:
            return _nothing_to_read()
        try:
            outcome = await tasks.extract(
                [tasks.DocumentLine(ln.page, ln.line, ln.text) for ln in lines],
                kind,
                provider=self._provider,
                gateway=self._gateway,
            )
        except tasks.ExtractionNotSupportedError:
            return _nothing_to_read()  # a type that is classified here and read by a later feature
        cfg = self._config or get_document_fields()
        call = outcome.calls[0]
        return ExtractionOutcome(
            fields=flatten_fields(doc_type, outcome.result.fields, cfg, tasks),
            signals=[signal.detail for signal in outcome.result.signals],
            provider=call.provider,
            model=call.model,
            prompt_id=call.prompt_id,
        )


def _nothing_to_read() -> ExtractionOutcome:
    """No model call was made: the type has no field schema."""
    return ExtractionOutcome({}, [], provider="none", model="none", prompt_id=None)


def get_extractor(mode: str | None = None) -> Extractor:
    """The extractor for this process: real when the task exists, else the fake (and say so)."""
    from app.services.fake_reader import FakeExtractor

    mode = mode or get_settings().pipeline_llm
    if mode != "fake":
        tasks = llm_tasks()
        if tasks is not None and hasattr(tasks, "extract"):
            logger.info("extract: using the real task (app.llm.tasks.extract)")
            return LlmExtractor()
    logger.warning("extract: using the rule-based fake reader (PIPELINE_LLM=%s)", mode)
    return FakeExtractor()

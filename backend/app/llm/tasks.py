"""Task functions: the typed entry points other modules call.

    classify()            Feature Design 1.5, Classify call
    extract()             Feature Design 1.5, Extract call (page batches merged in code)
    label_transactions()  Feature Design 3.5

They build prompt variables from document lines, call the gateway, and check
the reply against the input in code (for example, that cited line IDs exist).
They never do arithmetic on the values the model returns.
"""

from __future__ import annotations

import asyncio
import re
from collections.abc import Iterator, Sequence
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel

from app.llm.config import ConfigError
from app.llm.gateway import Gateway, GatewayResult, get_gateway
from app.prompts.schemas.classify import ClassifyResult
from app.prompts.schemas.fields import (
    ExtractedField,
    ExtractionResult,
    extraction_model,
    render_field_list,
)
from app.prompts.schemas.registry import REGISTRY, DocumentType, describe_types
from app.prompts.schemas.transactions import (
    LabelTransactionsResult,
    TransactionCategory,
)

# Feature Design 1.5: classify reads the first pages only.
CLASSIFY_PAGES = 2

# Every tag a prompt wraps untrusted text in. Text cannot close one of them early.
_CLOSING_TAG_RE = re.compile(
    r"</\s*(document|transactions|letter|application|flags|evidence)\s*>", re.IGNORECASE
)


@dataclass(frozen=True)
class DocumentLine:
    """One numbered OCR or text-layer line, as produced by ingestion."""

    page: int
    line: int
    text: str

    @property
    def line_id(self) -> str:
        return f"p{self.page}-L{self.line}"


def clean_text(text: str) -> str:
    """Flatten whitespace and defuse closing tags, so document text cannot leave its block."""
    return _CLOSING_TAG_RE.sub(lambda m: f"[/{m.group(1).lower()}]", " ".join(text.split()))


def format_numbered_lines(lines: Sequence[DocumentLine]) -> str:
    """``p1-L1: text`` per line; text is flattened and cannot close the document tag."""
    rendered = []
    for ln in lines:
        text = clean_text(ln.text)
        rendered.append(f"{ln.line_id}: {text}")
    return "\n".join(rendered)


@dataclass(frozen=True)
class ClassifyOutcome:
    result: ClassifyResult
    call: GatewayResult[ClassifyResult]
    # Cited line IDs that were not in the input; the caller flags these.
    unknown_line_ids: list[str]


async def classify(
    lines: Sequence[DocumentLine],
    *,
    provider: str | None = None,
    gateway: Gateway | None = None,
) -> ClassifyOutcome:
    """Classify a document from its first pages. The file name is never sent."""
    first_pages = [ln for ln in lines if ln.page <= CLASSIFY_PAGES]
    variables = {
        "type_descriptions": describe_types(),
        "numbered_lines": format_numbered_lines(first_pages),
    }
    call = await (gateway or get_gateway()).run(
        "classify", "classify@1", variables, ClassifyResult, provider=provider
    )
    known = {ln.line_id for ln in first_pages}
    unknown = [lid for lid in call.output.justification_line_ids if lid not in known]
    return ClassifyOutcome(result=call.output, call=call, unknown_line_ids=unknown)


# --- extract ---------------------------------------------------------------------------------


class ExtractionNotSupportedError(ValueError):
    """The type has no field schema (classified only here, or unrecognized)."""


_CERTAINTY_RANK = {"low": 0, "medium": 1, "high": 2}


@dataclass(frozen=True)
class FieldConflict:
    """Two page batches printed different values for one field. The first is kept, as low."""

    field: str
    lines: list[str]


@dataclass(frozen=True)
class ExtractOutcome:
    doc_type: DocumentType
    result: ExtractionResult
    calls: list[GatewayResult[ExtractionResult]]
    # Cited line IDs that were not in the lines sent; the caller flags these.
    unknown_line_ids: list[str]
    conflicts: list[FieldConflict] = field(default_factory=list)


def page_batches(lines: Sequence[DocumentLine], max_pages: int) -> list[list[DocumentLine]]:
    """Group lines into batches of at most ``max_pages`` pages, in page order."""
    pages = sorted({ln.page for ln in lines})
    batches = []
    for start in range(0, len(pages), max_pages):
        chunk = set(pages[start : start + max_pages])
        batches.append([ln for ln in lines if ln.page in chunk])
    return batches


def _batch_note(batch: Sequence[DocumentLine], total_pages: int, batched: bool) -> str:
    if not batched:
        return f"These are all {total_pages} page(s) of the document."
    pages = sorted({ln.page for ln in batch})
    return (
        f"These are pages {pages[0]} to {pages[-1]} of {total_pages}; the other pages are sent "
        "separately. Return null for fields that are not on these pages, and only the rows "
        "printed on these pages."
    )


def iter_extracted(model: BaseModel, prefix: str = "") -> Iterator[tuple[str, ExtractedField]]:
    """Every ``ExtractedField`` in a fields model, with its path (``earnings[0].current``)."""
    for name in type(model).model_fields:
        value = getattr(model, name)
        if isinstance(value, ExtractedField):
            yield prefix + name, value
        elif isinstance(value, list):
            for index, row in enumerate(value):
                if isinstance(row, BaseModel):
                    yield from iter_extracted(row, f"{prefix}{name}[{index}].")
        elif isinstance(value, BaseModel):
            yield from iter_extracted(value, f"{prefix}{name}.")


def cited_line_ids(result: ExtractionResult) -> list[str]:
    """Every line ID the result cites, from fields and signals, in order of first appearance."""
    cited = [lid for _, f in iter_extracted(result.fields) for lid in f.lines]
    cited += [lid for signal in result.signals for lid in signal.lines]
    return list(dict.fromkeys(cited))


def _same(a: str, b: str) -> bool:
    return " ".join(a.split()) == " ".join(b.split())


def _merge_field(
    values: list[ExtractedField], path: str, conflicts: list[FieldConflict]
) -> ExtractedField:
    found = [v for v in values if v.value is not None]
    if not found:
        return values[0]
    first = found[0]
    if all(_same(v.value or "", first.value or "") for v in found):
        # The same value printed in several batches (a header repeated on each page).
        lines = list(dict.fromkeys(lid for v in found for lid in v.lines))
        best = max(found, key=lambda v: _CERTAINTY_RANK[v.certainty])
        return ExtractedField(value=first.value, lines=lines, certainty=best.certainty)
    all_lines = list(dict.fromkeys(lid for v in found for lid in v.lines))
    conflicts.append(FieldConflict(path, all_lines))
    return ExtractedField(value=first.value, lines=first.lines, certainty="low")


def _merge_models(models: list[BaseModel], prefix: str, conflicts: list[FieldConflict]) -> Any:
    cls = type(models[0])
    data: dict[str, Any] = {}
    for name in cls.model_fields:
        values = [getattr(m, name) for m in models]
        first = values[0]
        if isinstance(first, ExtractedField):
            data[name] = _merge_field(values, prefix + name, conflicts)
        elif isinstance(first, list):
            data[name] = [row for value in values for row in value]  # rows in page order
        elif isinstance(first, BaseModel):
            data[name] = _merge_models(values, f"{prefix}{name}.", conflicts)
        else:
            data[name] = first
    return cls(**data)


def merge_extractions(
    batches: Sequence[ExtractionResult],
) -> tuple[ExtractionResult, list[FieldConflict]]:
    """Merge page-batch results in code (Feature Design 1.5).

    - A field takes the first non-null value in page order. If later batches print the
      same value, their lines are added; if they print a different value, the first is
      kept with certainty "low" and the field is reported as a conflict.
    - Repeating groups (rows) are joined in page order.
    - Signals from every batch are kept.
    """
    if not batches:
        raise ValueError("nothing to merge")
    conflicts: list[FieldConflict] = []
    fields = _merge_models([b.fields for b in batches], "", conflicts)
    signals = [signal for b in batches for signal in b.signals]
    merged = type(batches[0])(fields=fields, signals=signals)
    return merged, conflicts


async def extract(
    lines: Sequence[DocumentLine],
    doc_type: DocumentType,
    *,
    provider: str | None = None,
    gateway: Gateway | None = None,
) -> ExtractOutcome:
    """Read a document's fields with extract@1. Long documents go in page batches.

    The file name is never sent. Values come back exactly as printed; normalising and
    the arithmetic checks happen in code afterwards.
    """
    spec = REGISTRY.get(doc_type)
    if spec is None or spec.fields_model is None:
        raise ExtractionNotSupportedError(f"no field schema for document type '{doc_type}'")
    gw = gateway or get_gateway()
    settings = gw.config.extraction
    if settings is None:
        raise ConfigError("llm.yaml has no 'extraction' section")

    output_model = extraction_model(spec.fields_model)
    total_pages = len({ln.page for ln in lines})
    batches = page_batches(lines, settings.max_pages_per_call)
    batched = len(batches) > 1
    field_list = render_field_list(spec.fields_model)

    calls = await asyncio.gather(
        *(
            gw.run(
                "extract",
                "extract@1",
                {
                    "doc_type_label": spec.label,
                    "field_list": field_list,
                    "batch_note": _batch_note(batch, total_pages, batched),
                    "numbered_lines": format_numbered_lines(batch),
                },
                output_model,
                provider=provider,
            )
            for batch in batches
        )
    )

    unknown: list[str] = []
    for batch, call in zip(batches, calls, strict=True):
        sent = {ln.line_id for ln in batch}
        unknown += [lid for lid in cited_line_ids(call.output) if lid not in sent]

    if batched:
        result, conflicts = merge_extractions([c.output for c in calls])
    else:
        result, conflicts = calls[0].output, []
    return ExtractOutcome(
        doc_type=doc_type,
        result=result,
        calls=list(calls),
        unknown_line_ids=list(dict.fromkeys(unknown)),
        conflicts=conflicts,
    )


# --- label transactions ----------------------------------------------------------------------


@dataclass(frozen=True)
class TransactionInput:
    """One extracted transaction. Values are strings as printed; nothing is computed here."""

    line_id: str
    date: str
    description: str
    amount: str


@dataclass(frozen=True)
class LabeledTransaction:
    line_id: str
    category: TransactionCategory
    counterparty: str | None
    # True when the model never labelled it: shown as "other, needs review" (FD 3.5).
    needs_review: bool = False


@dataclass(frozen=True)
class LabelOutcome:
    labels: list[LabeledTransaction]  # one per input transaction, in input order
    calls: list[GatewayResult[LabelTransactionsResult]]
    # Line IDs the model returned that were not in the input; dropped and reported.
    unknown_line_ids: list[str]


def format_transactions(transactions: Sequence[TransactionInput]) -> str:
    return "\n".join(
        f"{t.line_id} | {clean_text(t.date)} | {clean_text(t.description)} | {clean_text(t.amount)}"
        for t in transactions
    )


async def label_transactions(
    transactions: Sequence[TransactionInput],
    *,
    borrower_names: Sequence[str],
    employer_names: Sequence[str],
    provider: str | None = None,
    gateway: Gateway | None = None,
) -> LabelOutcome:
    """One category and counterparty per transaction (Feature Design 3.5).

    If the reply misses transactions, the missing ones are sent once more; any still
    unlabelled come back as "other" with ``needs_review``. Unknown line IDs are dropped
    and reported. The first label for a line ID wins.
    """
    gw = gateway or get_gateway()
    wanted = {t.line_id for t in transactions}
    labels: dict[str, LabeledTransaction] = {}
    unknown: list[str] = []
    calls: list[GatewayResult[LabelTransactionsResult]] = []
    variables = {
        "categories": "\n".join(f"- {c.value}" for c in TransactionCategory),
        "borrower_names": ", ".join(clean_text(n) for n in borrower_names) or "(none given)",
        "employer_names": ", ".join(clean_text(n) for n in employer_names) or "(none given)",
    }

    pending = list(transactions)
    for _attempt in range(2):  # the first call, then one retry for any it missed
        if not pending:
            break
        call = await gw.run(
            "label_transactions",
            "label-transactions@1",
            {**variables, "transactions": format_transactions(pending)},
            LabelTransactionsResult,
            provider=provider,
        )
        calls.append(call)
        for label in call.output.labels:
            if label.line_id not in wanted:
                unknown.append(label.line_id)
            elif label.line_id not in labels:
                labels[label.line_id] = LabeledTransaction(
                    label.line_id, label.category, label.counterparty
                )
        pending = [t for t in pending if t.line_id not in labels]

    for t in pending:
        labels[t.line_id] = LabeledTransaction(
            t.line_id, TransactionCategory.OTHER, None, needs_review=True
        )
    return LabelOutcome(
        labels=[labels[t.line_id] for t in transactions],
        calls=calls,
        unknown_line_ids=list(dict.fromkeys(unknown)),
    )

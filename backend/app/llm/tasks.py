"""Task functions: the typed entry points other modules call (classify; extract on D3).

They build prompt variables from document lines, call the gateway, and check
the reply against the input in code (for example, that cited line IDs exist).
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass

from app.llm.gateway import Gateway, GatewayResult, get_gateway
from app.prompts.schemas.classify import ClassifyResult
from app.prompts.schemas.registry import describe_types

# Feature Design 1.5: classify reads the first pages only.
CLASSIFY_PAGES = 2

_CLOSING_TAG_RE = re.compile(r"</\s*document\s*>", re.IGNORECASE)


@dataclass(frozen=True)
class DocumentLine:
    """One numbered OCR or text-layer line, as produced by ingestion."""

    page: int
    line: int
    text: str

    @property
    def line_id(self) -> str:
        return f"p{self.page}-L{self.line}"


def format_numbered_lines(lines: Sequence[DocumentLine]) -> str:
    """``p1-L1: text`` per line; text is flattened and cannot close the document tag."""
    rendered = []
    for ln in lines:
        text = " ".join(ln.text.split())
        text = _CLOSING_TAG_RE.sub("[/document]", text)
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

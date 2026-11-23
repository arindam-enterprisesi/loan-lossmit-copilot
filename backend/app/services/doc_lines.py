"""A numbered line of a document, as the readers (classify, extract) receive it."""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass

_REF = re.compile(r"^p(\d+)-L(\d+)$")
PAGE_LABEL = re.compile(r"\bPage\s+(\d+)\s+of\s+(\d+)\b", re.IGNORECASE)


@dataclass(frozen=True)
class DocLine:
    page: int
    line: int
    text: str

    @property
    def ref(self) -> str:
        return f"p{self.page}-L{self.line}"


def parse_ref(ref: str) -> tuple[int, int] | None:
    """``"p1-L31"`` -> ``(1, 31)``."""
    found = _REF.match(ref)
    return (int(found.group(1)), int(found.group(2))) if found else None


def doc_lines(rows: Iterable[tuple[str, str]]) -> list[DocLine]:
    """Lines from ``(line_ref, text)`` pairs in page and line order; bad refs are skipped."""
    parsed = [(parse_ref(ref), text) for ref, text in rows]
    return sorted(
        (DocLine(page, line, text) for ref, text in parsed if ref for page, line in [ref]),
        key=lambda ln: (ln.page, ln.line),
    )


def printed_page_label(texts: Iterable[str]) -> str | None:
    """The "Page 1 of 3" printed on a page; the last one found counts, as it is a footer."""
    label = None
    for text in texts:
        found = PAGE_LABEL.search(text)
        if found:
            label = found.group(0)
    return label

"""Shared helpers for the synthetic-data tests.

The generator lives in ``data/synthetic`` (outside the backend package), so put ``data/``
on the path. Expected values in the tests are typed in from the Feature Design on purpose:
they are the ground truth the scenario files must reproduce, never read back from them.
"""

from __future__ import annotations

import sys
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parents[3] / "data"
if str(DATA_DIR) not in sys.path:
    sys.path.insert(0, str(DATA_DIR))

import pdfplumber  # noqa: E402

D = Decimal


def q(value: Decimal) -> Decimal:
    """Round to cents the way the illustrative methods do (half up)."""
    return value.quantize(D("0.01"), ROUND_HALF_UP)


def pct(numerator: Decimal, denominator: Decimal) -> Decimal:
    return q(numerator / denominator * 100)


def fmt(value: Decimal) -> str:
    """2033.61 -> '2,033.61' (how amounts are printed in the documents)."""
    return f"{value:,.2f}"


def read_pages(path: Path, password: str | None = None) -> list[list[str]]:
    """The text layer of a PDF: one list of lines per page, in reading order.

    The nth line of page p is the line ``p<p>-L<n>`` of the Feature Design.
    """
    with pdfplumber.open(str(path), password=password) as pdf:
        return [(page.extract_text() or "").split("\n") for page in pdf.pages]


def flat(pages: list[list[str]]) -> str:
    return "\n".join("\n".join(lines) for lines in pages)

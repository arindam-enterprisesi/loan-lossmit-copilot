"""Synthetic sample documents as numbered lines, for the smoke CLI, tests and evaluation.

Each JSON file was made from a scenario in ``data/synthetic/scenarios`` by Abhay's
generator and read by ``app.services.ingestion.parse_pdf``, so the line IDs match
what ingestion stores. All people and figures are invented.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from app.llm.tasks import DocumentLine, TransactionInput

SAMPLES_DIR = Path(__file__).resolve().parent


def load_lines(name: str) -> list[DocumentLine]:
    """``load_lines("daniel_pay_stub")`` reads ``daniel_pay_stub_lines.json``."""
    raw = json.loads((SAMPLES_DIR / f"{name}_lines.json").read_text(encoding="utf-8"))
    return [DocumentLine(row["page"], row["line"], row["text"]) for row in raw["lines"]]


_TRANSACTION_ROW = re.compile(
    r"^(?P<date>\d{4}-\d{2}-\d{2}) (?P<description>.+?) (?P<amount>-?[\d,]+\.\d\d) "
    r"(?P<balance>-?[\d,]+\.\d\d)$"
)


def sample_transactions(name: str) -> list[TransactionInput]:
    """Transaction rows of a sample statement, split by pattern (for smoke and tests only).

    In the product, transactions come from extract@1; this shortcut keeps the label
    check independent of the extract call.
    """
    rows = []
    for ln in load_lines(name):
        match = _TRANSACTION_ROW.match(ln.text)
        if match:
            rows.append(
                TransactionInput(ln.line_id, match["date"], match["description"], match["amount"])
            )
    return rows

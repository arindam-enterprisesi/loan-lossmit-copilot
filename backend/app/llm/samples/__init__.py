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
from app.prompts.schemas.income import IncomeEvidence, IncomeFlag

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


def daniel_income_inputs() -> tuple[list[IncomeFlag], list[IncomeEvidence]]:
    """Daniel Reyes's deferral flag (Feature Design 2.8 example), as the income service sends it.

    Figures come from ``data/synthetic/scenarios/daniel_reyes.json`` (W-2 2025). The gap
    is calculated in code; the model only explains it, citing Box 12.
    """
    flags = [
        IncomeFlag(
            "INC-DEFERRALS",
            "W-2 2025: Box 5 Medicare wages are higher than Box 1 wages",
            ["w2_2025.box1", "w2_2025.box5", "w2_2025.box5_minus_box1"],
        )
    ]
    evidence = [
        IncomeEvidence("w2_2025.employer", "W-2 2025 employer", "Cedar Valley Manufacturing, Inc."),
        IncomeEvidence(
            "w2_2025.box1", "W-2 2025 Box 1, wages, tips, other compensation", "69,840.68"
        ),
        IncomeEvidence("w2_2025.box5", "W-2 2025 Box 5, Medicare wages and tips", "74,298.60"),
        IncomeEvidence(
            "w2_2025.box5_minus_box1", "W-2 2025 Box 5 minus Box 1 (calculated in code)", "4,457.92"
        ),
        IncomeEvidence("w2_2025.box12", "W-2 2025 Box 12, code D", "4,457.92"),
        IncomeEvidence(
            "pay_stub_2026-09-27.deductions",
            "Deduction lines on the latest pay stub",
            "401(k) deferral; Health insurance (pre-tax)",
        ),
    ]
    return flags, evidence

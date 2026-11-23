"""Labelling bank statement lines (Feature Design 3.5): one category and counterparty per line.

A ``TransactionLabeller`` turns a statement's lines into labels. Two exist:

* ``LlmLabeller`` calls Arindam's ``label_transactions`` task (one call per statement; the retry for
  missed lines and the "other, needs review" fallback are in his function). It is the real one.
* ``FakeLabeller`` is a small keyword rule set for ``PIPELINE_LLM=fake``, so the demo and the tests
  run with no provider. It labels the generated scenarios correctly and has no judgement beyond the
  keywords: anything it does not recognise is "other". It is a stand-in (docs/build-log.md).

The labels are data for the asset analysis; the model never does any arithmetic (rule 1).
"""

from __future__ import annotations

import logging
import re
from collections.abc import Sequence
from typing import Protocol

from app.llm.gateway import Gateway
from app.llm.tasks import LabeledTransaction, TransactionInput, label_transactions
from app.prompts.schemas.transactions import TransactionCategory
from app.settings import get_settings

logger = logging.getLogger(__name__)

NOISE_WORDS = {"payment", "pmt", "payroll", "rent", "ref", "t"}


class TransactionLabeller(Protocol):
    async def label(
        self,
        transactions: Sequence[TransactionInput],
        *,
        borrower_names: Sequence[str],
        employer_names: Sequence[str],
    ) -> list[LabeledTransaction]:
        """One label per input line, in input order."""
        ...


class LlmLabeller:
    """The real labeller: Arindam's task through the gateway."""

    def __init__(self, provider: str | None = None, gateway: Gateway | None = None) -> None:
        self.provider = provider
        self.gateway = gateway

    async def label(
        self,
        transactions: Sequence[TransactionInput],
        *,
        borrower_names: Sequence[str],
        employer_names: Sequence[str],
    ) -> list[LabeledTransaction]:
        if not transactions:
            return []
        outcome = await label_transactions(
            transactions,
            borrower_names=borrower_names,
            employer_names=employer_names,
            provider=self.provider,
            gateway=self.gateway,
        )
        return outcome.labels


# --- the fake --------------------------------------------------------------------------------

C = TransactionCategory
# Checked in order; the first rule whose words are in the description wins.
DEBIT_RULES: list[tuple[TransactionCategory, tuple[str, ...]]] = [
    (C.OVERDRAFT_OR_RETURNED_ITEM_FEE, ("overdraft", "nsf", "returned item")),
    (C.OTHER_FEE, ("fee",)),
    (C.TRANSFER_OUT, ("zelle to", "transfer to", "venmo to")),
    (C.HOUSING_PAYMENT, ("rent", "mortgage", "apartments")),
    (C.CREDIT_CARD_PAYMENT, ("card payment", "card pmt", "visa pmt", "mastercard pmt")),
    (C.LOAN_PAYMENT, ("auto finance", "auto credit", "student loan", "loan")),
    (C.INSURANCE, ("insurance",)),
    (
        C.UTILITY,
        ("electric", "water", "power", "gas &", "internet", "wireless", "fiber", "utilit"),
    ),
    (
        C.EVERYDAY_SPENDING,
        (
            "aldi",
            "kroger",
            "giant eagle",
            "meijer",
            "panera",
            "chipotle",
            "dominos",
            "speedway",
            "shell",
            "marathon",
            "cvs",
            "tap house",
            "grocery",
            "restaurant",
            "pharmacy",
        ),
    ),
]
CREDIT_RULES: list[tuple[TransactionCategory, tuple[str, ...]]] = [
    (C.PAYROLL_DEPOSIT, ("payroll",)),
    (C.REFUND, ("refund",)),
    (C.TRANSFER_IN, ("zelle from", "transfer from", "venmo from")),
]


def _words(description: str) -> str:
    return " ".join(re.findall(r"[a-z0-9&]+", description.lower()))


def _counterparty(description: str) -> str | None:
    """A readable payee: the name in a transfer, else the description without store numbers."""
    text = description
    if re.match(r"\s*(zelle|transfer|venmo)", description, re.I):
        named = re.search(r"\b(?:from|to)\s+(.+?)(?:\s+ref\b.*)?$", description, re.I)
        text = named.group(1) if named else description
    kept = [
        w
        for w in re.findall(r"[A-Za-z&][A-Za-z&'.-]*", text)
        if w.lower().strip(".") not in NOISE_WORDS
    ]
    return " ".join(w.capitalize() if w.isupper() and w != "&" else w for w in kept) or None


class FakeLabeller:
    """Keyword rules, no model. The direction comes from the sign printed on the amount."""

    async def label(
        self,
        transactions: Sequence[TransactionInput],
        *,
        borrower_names: Sequence[str],
        employer_names: Sequence[str],
    ) -> list[LabeledTransaction]:
        del borrower_names, employer_names
        return [self._one(t) for t in transactions]

    @staticmethod
    def _one(t: TransactionInput) -> LabeledTransaction:
        words = _words(t.description)
        credit = not t.amount.strip().startswith("-")
        rules = CREDIT_RULES if credit else DEBIT_RULES
        category = next(
            (cat for cat, keys in rules if any(k in words for k in keys)),
            C.OTHER_INCOME_DEPOSIT if credit else C.OTHER,
        )
        return LabeledTransaction(t.line_id, category, _counterparty(t.description))


def get_labeller(mode: str | None = None) -> TransactionLabeller:
    """The labeller for this process: the real task, or keyword rules for ``PIPELINE_LLM=fake``."""
    mode = mode or get_settings().pipeline_llm
    if mode == "fake":
        logger.warning("label: using the rule-based fake labeller (PIPELINE_LLM=%s)", mode)
        return FakeLabeller()
    return LlmLabeller()

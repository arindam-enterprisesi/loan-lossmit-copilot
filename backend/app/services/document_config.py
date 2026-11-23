"""Settings for reading documents: ``validation.yaml`` and ``document_fields.yaml``.

Both are versioned and labelled illustrative or authoritative (CLAUDE.md rule 4). The checks
look fields up by role through ``DocumentFieldsConfig``, so renaming a field is a YAML change only.
"""

from __future__ import annotations

import re
from decimal import Decimal
from functools import lru_cache
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

CONFIG_DIR = Path(__file__).resolve().parents[2] / "config"
DEFAULT_VALIDATION_PATH = CONFIG_DIR / "validation.yaml"
DEFAULT_FIELDS_PATH = CONFIG_DIR / "document_fields.yaml"

Kind = Literal["amount", "date", "text", "id_last4", "number"]
Severity = Literal["error", "warning", "info"]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


# --- validation.yaml ------------------------------------------------------------------------


class FlagTemplate(_Strict):
    severity: Severity
    message: str


class ValidationConfig(_Strict):
    version: str
    label: Literal["illustrative", "authoritative"]
    arithmetic_tolerance: Decimal = Field(gt=0)
    min_line_confidence: Decimal = Field(ge=0, le=1)
    flags: dict[str, FlagTemplate]

    @model_validator(mode="after")
    def _needs_the_cannot_check_template(self) -> ValidationConfig:
        if "cannot_check" not in self.flags:
            raise ValueError("flags must define cannot_check")
        return self

    def severity(self, code: str) -> Severity:
        return self.flags[code].severity

    def flag(self, code: str, **values: object) -> tuple[Severity, str]:
        """The severity and filled-in message for ``code`` (or ``code:variant``)."""
        template = self.flags[code]
        return template.severity, template.message.format(**values)


# --- document_fields.yaml -------------------------------------------------------------------


class FieldSpec(_Strict):
    name: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    label: str
    kind: Kind
    required: bool = False


class EarningsSpec(_Strict):
    prefix: str
    suffix: str


class TransactionSpec(_Strict):
    """Each transaction is four fields: ``<prefix><n>_<part>`` for the four parts."""

    prefix: str
    date: str
    description: str
    amount: str
    balance: str


class RowSpec(_Strict):
    """A repeating group of the extract schema (earnings lines, transactions, Box 12 entries).

    Each row of ``source`` becomes fields named ``<prefix><nnn>_<part>`` (``earnings_001_hours``),
    numbered from 001 in document order. ``parts`` gives each column's kind. When the statement has
    separate deposit and withdrawal columns, ``sign_column`` names the part holding the column
    heading, and the sign of ``amount_part`` follows it (``TypeSpec.column_signs``).
    """

    source: str
    prefix: str
    parts: dict[str, Kind]
    sign_column: str | None = None
    amount_part: str | None = None

    def field_name(self, index: int, part: str) -> str:
        return f"{self.prefix}{index:03d}_{part}"


class ColumnSigns(_Strict):
    """Words in a column heading that make an amount a debit (negative) or a credit (positive)."""

    negative: list[str]
    positive: list[str]


class TypeSpec(_Strict):
    label: str
    summary: str | None = None
    borrower_field: str | None = None
    period_fields: list[str] = Field(default_factory=list)
    roles: dict[str, str] = Field(default_factory=dict)
    earnings: EarningsSpec | None = None
    transactions: TransactionSpec | None = None
    fields: list[FieldSpec] = Field(default_factory=list)
    # The extract schema's names where they differ from the names used here (his -> ours).
    renames: dict[str, str] = Field(default_factory=dict)
    rows: list[RowSpec] = Field(default_factory=list)
    column_signs: ColumnSigns | None = None


_TRANSACTION_KINDS: dict[str, Kind] = {
    "date": "date",
    "description": "text",
    "amount": "amount",
    "balance": "amount",
}


class DocumentFieldsConfig(_Strict):
    version: str
    label: Literal["illustrative", "authoritative"]
    types: dict[str, TypeSpec]

    def spec(self, doc_type: str) -> TypeSpec | None:
        return self.types.get(doc_type)

    def type_label(self, doc_type: str) -> str:
        spec = self.types.get(doc_type)
        return spec.label if spec else doc_type.replace("_", " ")

    def has_fields(self, doc_type: str) -> bool:
        spec = self.types.get(doc_type)
        return bool(spec and (spec.fields or spec.transactions))

    def role(self, doc_type: str, role: str) -> str | None:
        spec = self.types.get(doc_type)
        return spec.roles.get(role) if spec else None

    def required_fields(self, doc_type: str) -> list[FieldSpec]:
        spec = self.types.get(doc_type)
        return [f for f in spec.fields if f.required] if spec else []

    def field_spec(self, doc_type: str, name: str) -> FieldSpec | None:
        spec = self.types.get(doc_type)
        return next((f for f in spec.fields if f.name == name), None) if spec else None

    def field_label(self, doc_type: str, name: str) -> str:
        found = self.field_spec(doc_type, name)
        if found:
            return found.label
        match = self.transaction_match(doc_type, name)
        if match:
            return f"Transaction {int(match[0])} {match[1]}"
        return name.replace("_", " ").capitalize()

    def transaction_match(self, doc_type: str, name: str) -> tuple[str, str] | None:
        """``("001", "amount")`` if ``name`` is a transaction field of this type, else None."""
        spec = self.types.get(doc_type)
        if spec is None or spec.transactions is None:
            return None
        tx = spec.transactions
        parts = {
            tx.date: "date",
            tx.description: "description",
            tx.amount: "amount",
            tx.balance: "balance",
        }
        pattern = re.compile(rf"^{re.escape(tx.prefix)}(\d+)_({'|'.join(map(re.escape, parts))})$")
        found = pattern.match(name)
        return (found.group(1), parts[found.group(2)]) if found else None

    def is_earnings_field(self, doc_type: str, name: str) -> bool:
        spec = self.types.get(doc_type)
        if spec is None or spec.earnings is None:
            return False
        e = spec.earnings
        return (
            name.startswith(e.prefix)
            and name.endswith(e.suffix)
            and len(name) > len(e.prefix) + len(e.suffix)
        )

    def kind_of(self, doc_type: str, name: str) -> Kind:
        found = self.field_spec(doc_type, name)
        if found:
            return found.kind
        match = self.transaction_match(doc_type, name)
        if match:
            return _TRANSACTION_KINDS[match[1]]
        if self.is_earnings_field(doc_type, name):
            return "amount"
        found_row = self.row_match(doc_type, name)
        if found_row:
            row, _, part = found_row
            return row.parts[part]
        return "text"

    def rows(self, doc_type: str) -> list[RowSpec]:
        spec = self.types.get(doc_type)
        return list(spec.rows) if spec else []

    def row_match(self, doc_type: str, name: str) -> tuple[RowSpec, int, str] | None:
        """``(row, 1, "hours")`` if ``name`` is one column of a repeating row of this type."""
        for row in self.rows(doc_type):
            parts = "|".join(map(re.escape, row.parts))
            found = re.match(rf"^{re.escape(row.prefix)}(\d+)_({parts})$", name)
            if found:
                return row, int(found.group(1)), found.group(2)
        return None

    def rename(self, doc_type: str, name: str) -> str:
        """The name used here for a field the extract schema calls ``name``."""
        spec = self.types.get(doc_type)
        return spec.renames.get(name, name) if spec else name

    def is_column_signed(self, doc_type: str, name: str) -> bool:
        """Is this an amount whose sign comes from a column heading, so it prints unsigned?"""
        found = self.row_match(doc_type, name)
        return bool(found and found[0].sign_column and found[2] == found[0].amount_part)

    def sign_for_column(self, doc_type: str, heading: str | None) -> Literal["-", "+"] | None:
        """``"-"`` for a debit column heading, ``"+"`` for a credit one, None if unknown."""
        spec = self.types.get(doc_type)
        if spec is None or spec.column_signs is None or not heading:
            return None
        text = heading.lower()
        if any(word.lower() in text for word in spec.column_signs.negative):
            return "-"
        if any(word.lower() in text for word in spec.column_signs.positive):
            return "+"
        return None

    def transaction_field(self, doc_type: str, index: int | str, part: str) -> str | None:
        """The field name for one part (date, description, amount, balance) of a transaction."""
        spec = self.types.get(doc_type)
        if spec is None or spec.transactions is None:
            return None
        tx = spec.transactions
        suffix = {
            "date": tx.date,
            "description": tx.description,
            "amount": tx.amount,
            "balance": tx.balance,
        }[part]
        return f"{tx.prefix}{int(index):03d}_{suffix}"


# --- loading --------------------------------------------------------------------------------


def load_validation_config(path: Path | None = None) -> ValidationConfig:
    with (path or DEFAULT_VALIDATION_PATH).open(encoding="utf-8") as fh:
        return ValidationConfig.model_validate(yaml.safe_load(fh))


def load_document_fields(path: Path | None = None) -> DocumentFieldsConfig:
    with (path or DEFAULT_FIELDS_PATH).open(encoding="utf-8") as fh:
        return DocumentFieldsConfig.model_validate(yaml.safe_load(fh))


@lru_cache
def get_validation_config() -> ValidationConfig:
    return load_validation_config()


@lru_cache
def get_document_fields() -> DocumentFieldsConfig:
    return load_document_fields()

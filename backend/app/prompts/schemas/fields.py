"""Building blocks for extraction schemas (Feature Design 1.3 and 1.5, Extract call).

Every extracted value is an ``ExtractedField``: the text exactly as printed, the
line IDs it was read from, and the model's certainty. The model never converts,
adds up or compares values; code does that afterwards.

Schemas are written so every provider's strict JSON-schema mode accepts them:
every property is required (absent values are ``null``, never omitted) and no
object allows extra keys. Field guidance for the prompt is attached with
``Describe`` inside ``Annotated``, which Pydantic leaves out of the JSON schema,
so the schema stays a plain shape with no ``$ref`` siblings.
"""

from __future__ import annotations

import typing
from dataclasses import dataclass
from functools import cache
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, create_model

Certainty = Literal["high", "medium", "low"]


class Schema(BaseModel):
    """Base for every extraction model: no extra keys, so ``additionalProperties`` is false."""

    model_config = ConfigDict(extra="forbid")


@dataclass(frozen=True)
class Describe:
    """Guidance for one field, shown to the model in the field list (not in the JSON schema)."""

    text: str


class ExtractedField(Schema):
    value: str | None
    lines: list[str]
    certainty: Certainty


SignalKind = Literal["continued_notice", "cut_off_table", "page_count_mismatch", "other"]


class Signal(Schema):
    """A sign that the document may be incomplete, cited to the lines that show it."""

    kind: SignalKind
    detail: str
    lines: list[str]


class ExtractionResult(Schema):
    """Base of every per-type extraction result: ``{fields: {...}, signals: [...]}``."""

    fields: Any
    signals: list[Signal]


@cache
def extraction_model(fields_model: type[Schema]) -> type[ExtractionResult]:
    """The output model for one document type.

    Built with an explicit, plain name (``PayStubFieldsExtraction``): provider
    schema names must match ``[A-Za-z0-9_-]+``, which a generic's
    ``ExtractionResult[PayStubFields]`` does not.
    """
    model: type[ExtractionResult] = create_model(
        f"{fields_model.__name__}Extraction",
        __base__=ExtractionResult,
        fields=(fields_model, ...),
        signals=(list[Signal], ...),
    )
    return model


# --- field list for the prompt ----------------------------------------------------------------


def _describe(metadata: list[Any]) -> str | None:
    return next((m.text for m in metadata if isinstance(m, Describe)), None)


def _row_model(annotation: Any) -> type[Schema] | None:
    """The row model of a ``list[Row]`` annotation, or None."""
    if typing.get_origin(annotation) is list:
        (item,) = typing.get_args(annotation)
        if isinstance(item, type) and issubclass(item, Schema):
            return item
    return None


def undescribed_fields(model: type[Schema], prefix: str = "") -> list[str]:
    """Field paths with no ``Describe`` guidance (a test keeps this empty)."""
    missing: list[str] = []
    for name, info in model.model_fields.items():
        if _describe(info.metadata) is None:
            missing.append(prefix + name)
        row = _row_model(info.annotation)
        if row is not None:
            missing.extend(undescribed_fields(row, f"{prefix}{name}[]."))
    return missing


def render_field_list(model: type[Schema], indent: str = "") -> str:
    """One bullet per field with its guidance; repeating groups list their columns."""
    out: list[str] = []
    for name, info in model.model_fields.items():
        text = _describe(info.metadata) or ""
        row = _row_model(info.annotation)
        if row is None:
            out.append(f"{indent}- {name}: {text}")
        else:
            out.append(f"{indent}- {name} (one entry per row, in document order): {text}")
            out.append(render_field_list(row, indent + "    "))
    return "\n".join(out)

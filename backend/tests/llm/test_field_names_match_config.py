"""Every extract schema emits the field names the pipeline stores (config/document_fields.yaml).

The pipeline flattens a schema's nested result into named fields (``score_001_value``); the
checks and analyses look those names up. A schema field the config does not know would be
stored under a name nothing reads, so the two must agree.
"""

from typing import Any, get_args, get_origin

import pytest

from app.prompts.schemas.fields import ExtractedField
from app.prompts.schemas.registry import REGISTRY, DocumentType
from app.services.document_config import get_document_fields

CONFIG = get_document_fields()


def _inner(annotation: Any) -> Any:
    # Annotated[X, Describe(...)] -> X
    args = get_args(annotation)
    return args[0] if args and not isinstance(annotation, type) else annotation


def schema_names(model: Any) -> tuple[set[str], dict[str, set[str]]]:
    scalars: set[str] = set()
    rows: dict[str, set[str]] = {}
    for name, info in model.model_fields.items():
        kind = info.annotation
        if kind is ExtractedField:
            scalars.add(name)
        elif get_origin(kind) is list:
            (row_model,) = get_args(kind)
            rows[name] = set(row_model.model_fields)
    return scalars, rows


EXTRACTED = [t for t, spec in REGISTRY.items() if spec.fields_model is not None]


@pytest.mark.parametrize("doc_type", EXTRACTED, ids=lambda t: t.value)
def test_schema_names_are_known_to_the_pipeline(doc_type: DocumentType) -> None:
    spec = CONFIG.spec(doc_type.value)
    assert spec is not None, f"{doc_type} has a schema but no entry in document_fields.yaml"
    if not spec.fields and not spec.rows:
        pytest.skip(
            f"{doc_type} lists no fields yet: its names are stored as the schema gives them"
        )
    model = REGISTRY[doc_type].fields_model
    scalars, rows = schema_names(model)

    configured = {f.name for f in spec.fields}
    renamed = {CONFIG.rename(doc_type.value, name) for name in scalars}
    unknown = sorted(renamed - configured - set(spec.period_fields) - set(spec.roles.values()))
    assert unknown == [], f"{doc_type}: scalar fields not in the config: {unknown}"

    row_specs = {row.source: row for row in CONFIG.rows(doc_type.value)}
    for source, parts in rows.items():
        if source in ("earnings", "deductions") or (
            spec.transactions and source == "transactions" and source not in row_specs
        ):
            continue  # older dedicated layouts (EarningsSpec, TransactionSpec)
        assert source in row_specs, f"{doc_type}: list {source} has no rows entry"
        assert parts <= set(row_specs[source].parts), (
            f"{doc_type}.{source}: parts not in the config: "
            f"{sorted(parts - set(row_specs[source].parts))}"
        )


def test_credit_report_matches_the_feature_4_fields() -> None:
    scalars, rows = schema_names(REGISTRY[DocumentType.CREDIT_REPORT].fields_model)
    assert scalars == {"consumer_name", "report_date", "alerts"}
    assert set(rows) == {"scores", "tradelines", "inquiries"}
    assert "monthly_payment" in rows["tradelines"]

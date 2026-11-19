"""The document endpoints agree with contracts/openapi.yaml: names, shapes and routes."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

from app.api.schemas.extraction import (
    ExtractionOut,
    FieldOut,
    FieldReviewIn,
    TypeChangeAccepted,
    TypeChangeIn,
)
from app.db.enums import FlagSeverity
from app.main import API_PREFIX, app

CONTRACT = Path(__file__).resolve().parents[3] / "contracts" / "openapi.yaml"


@pytest.fixture(scope="module")
def spec() -> dict[str, Any]:
    return yaml.safe_load(CONTRACT.read_text(encoding="utf-8"))  # type: ignore[no-any-return]


def _props(schema: dict[str, Any]) -> set[str]:
    return set(schema["properties"])


def test_field_and_extraction_use_the_contracts_names(spec: dict[str, Any]) -> None:
    schemas = spec["components"]["schemas"]
    assert set(FieldOut.model_fields) == _props(schemas["Field"])
    assert set(ExtractionOut.model_fields) == _props(schemas["Extraction"])


def test_the_required_parts_of_a_field_and_an_extraction_are_always_sent(
    spec: dict[str, Any],
) -> None:
    schemas = spec["components"]["schemas"]
    for model, name in ((FieldOut, "Field"), (ExtractionOut, "Extraction")):
        required = set(schemas[name]["required"])
        sent = {n for n, f in model.model_fields.items() if f.is_required()}
        assert required <= sent, (name, required - sent)


def test_field_review_matches_the_contract(spec: dict[str, Any]) -> None:
    contract = spec["components"]["schemas"]["FieldReview"]
    assert set(FieldReviewIn.model_fields) == _props(contract)
    assert contract["required"] == ["action", "expected_version"]
    ours = FieldReviewIn.model_json_schema()
    assert ours["properties"]["action"]["enum"] == contract["properties"]["action"]["enum"]
    assert (
        ours["properties"]["reason"]["anyOf"][0]["maxLength"]
        == contract["properties"]["reason"]["maxLength"]
    )


def test_set_document_type_matches_the_contract(spec: dict[str, Any]) -> None:
    operation = spec["paths"]["/cases/{case_id}/documents/{document_id}/type"]["put"]
    request = operation["requestBody"]["content"]["application/json"]["schema"]
    assert set(TypeChangeIn.model_fields) == _props(request) == {"doc_type", "reason"}
    assert request["required"] == ["doc_type"]
    reason = TypeChangeIn.model_json_schema()["properties"]["reason"]["anyOf"][0]
    assert reason["maxLength"] == request["properties"]["reason"]["maxLength"]
    accepted = operation["responses"]["202"]["content"]["application/json"]["schema"]
    assert set(TypeChangeAccepted.model_fields) == _props(accepted) == set(accepted["required"])


def test_flag_severities_are_the_contracts(spec: dict[str, Any]) -> None:
    assert [s.value for s in FlagSeverity] == spec["components"]["schemas"]["Severity"]["enum"]


IMPLEMENTED = {
    "uploadDocuments",
    "listDocuments",
    "getExtraction",
    "reviewField",
    "setDocumentType",
    "getJob",
}


def test_every_contract_operation_in_this_area_is_implemented_at_its_path(
    spec: dict[str, Any],
) -> None:
    served = {
        (op["operationId"], path, method.upper())
        for path, item in app.openapi()["paths"].items()
        for method, op in item.items()
        if isinstance(op, dict) and "operationId" in op
    }
    wanted = {
        (op["operationId"], API_PREFIX + path, method.upper())
        for path, item in spec["paths"].items()
        for method, op in item.items()
        if isinstance(op, dict) and op.get("operationId") in IMPLEMENTED
    }
    assert {w[0] for w in wanted} == IMPLEMENTED
    assert wanted <= served, wanted - served

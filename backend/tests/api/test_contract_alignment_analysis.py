"""The completeness endpoints agree with contracts/openapi.yaml; income has none there yet.

``POST /cases/{id}/completeness`` and ``GET .../completeness/latest`` are in the contract and must
match it exactly. The income endpoints and the completeness override are not (only a TODO comment
for income, and ``override_reason`` on the item with no endpoint to set it), so the contract is
checked for what it does say, and the new paths are checked not to collide with anything it names.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

from app.api.schemas.completeness import (
    CompletenessItemOut,
    CompletenessResultOut,
    CompletenessRunIn,
)
from app.main import API_PREFIX, app

CONTRACT = Path(__file__).resolve().parents[3] / "contracts" / "openapi.yaml"


@pytest.fixture(scope="module")
def spec() -> dict[str, Any]:
    return yaml.safe_load(CONTRACT.read_text(encoding="utf-8"))  # type: ignore[no-any-return]


def test_the_result_and_its_items_use_the_contracts_names(spec: dict[str, Any]) -> None:
    schemas = spec["components"]["schemas"]
    assert set(CompletenessResultOut.model_fields) == set(
        schemas["CompletenessResult"]["properties"]
    )
    assert set(CompletenessItemOut.model_fields) == set(schemas["CompletenessItem"]["properties"])


def test_every_required_part_is_always_sent(spec: dict[str, Any]) -> None:
    schemas = spec["components"]["schemas"]
    for model, name in (
        (CompletenessResultOut, "CompletenessResult"),
        (CompletenessItemOut, "CompletenessItem"),
    ):
        required = set(schemas[name]["required"])
        always = {n for n, f in model.model_fields.items() if f.is_required()}
        assert required <= always, (name, required - always)


def test_the_statuses_sent_are_values_the_contract_allows(spec: dict[str, Any]) -> None:
    schemas = spec["components"]["schemas"]
    contract_items = set(schemas["CompletenessItemStatus"]["enum"])
    ours_items = set(CompletenessItemOut.model_json_schema()["properties"]["status"]["enum"])
    assert ours_items == contract_items  # satisfied, partial, missing, overridden
    ours_overall = set(
        CompletenessResultOut.model_json_schema()["properties"]["overall_status"]["enum"]
    )
    assert ours_overall == set(
        schemas["CompletenessResult"]["properties"]["overall_status"]["enum"]
    )
    label = set(CompletenessResultOut.model_json_schema()["properties"]["checklist_label"]["enum"])
    assert label == set(schemas["CompletenessResult"]["properties"]["checklist_label"]["enum"])


def test_running_a_checklist_takes_what_the_contract_says(spec: dict[str, Any]) -> None:
    operation = spec["paths"]["/cases/{case_id}/completeness"]["post"]
    request = operation["requestBody"]["content"]["application/json"]["schema"]
    assert set(CompletenessRunIn.model_fields) == set(request["properties"]) == {"checklist_id"}
    assert request["required"] == ["checklist_id"]
    assert "200" in operation["responses"] and "422" in operation["responses"]


def test_the_contract_operations_are_served_at_their_paths(spec: dict[str, Any]) -> None:
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
        if isinstance(op, dict)
        and op.get("operationId") in {"runCompleteness", "getLatestCompleteness"}
    }
    assert len(wanted) == 2 and wanted <= served, wanted - served


def test_the_new_endpoints_do_not_collide_with_anything_the_contract_names(
    spec: dict[str, Any],
) -> None:
    contract_ids = {
        op["operationId"]
        for item in spec["paths"].values()
        for op in item.values()
        if isinstance(op, dict) and "operationId" in op
    }
    ours = {
        "runIncomeAnalysis",
        "getLatestIncomeAnalysis",
        "reviewIncomeComponent",
        "overrideCompletenessItem",
    }
    assert not ours & contract_ids  # not in the contract yet: Arindam adds them
    served = {
        op["operationId"]
        for item in app.openapi()["paths"].values()
        for op in item.values()
        if isinstance(op, dict) and "operationId" in op
    }
    assert ours <= served

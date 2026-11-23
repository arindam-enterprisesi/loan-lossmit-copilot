"""The case response agrees with contracts/openapi.yaml (``Case``), including ``case_ref``."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest
import yaml

from app.api.schemas.cases import CaseOut

CONTRACT = Path(__file__).resolve().parents[3] / "contracts" / "openapi.yaml"


@pytest.fixture(scope="module")
def spec() -> dict[str, Any]:
    return yaml.safe_load(CONTRACT.read_text(encoding="utf-8"))  # type: ignore[no-any-return]


def test_a_case_has_every_property_the_contract_names(spec: dict[str, Any]) -> None:
    schemas = spec["components"]["schemas"]
    contract = set(schemas["CaseCreate"]["properties"])
    contract |= set(schemas["Case"]["allOf"][1]["properties"])
    assert set(CaseOut.model_fields) == contract


def test_the_required_parts_of_a_case_are_always_sent(spec: dict[str, Any]) -> None:
    schemas = spec["components"]["schemas"]
    required = set(schemas["CaseCreate"]["required"]) | set(schemas["Case"]["allOf"][1]["required"])
    always = {name for name, field in CaseOut.model_fields.items() if field.is_required()}
    assert required <= always


def test_case_ref_follows_the_contracts_pattern(spec: dict[str, Any]) -> None:
    pattern = spec["components"]["schemas"]["Case"]["allOf"][1]["properties"]["case_ref"]["pattern"]
    assert re.fullmatch(pattern, "LP-0001") and re.fullmatch(pattern, "LM-12345")
    assert not re.fullmatch(pattern, "XX-0001") and not re.fullmatch(pattern, "LP-1")

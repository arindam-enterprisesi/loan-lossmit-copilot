"""The code agrees with contracts/openapi.yaml where the contract is the source of truth.

The schema doc (docs/database-schema.md) differs from the contract on a few enum values (roles,
pillars, review statuses). The rule is that the contract wins on enum values and API names, so
these tests read the contract and fail if the code drifts from it. They need no database.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any

import pytest
import yaml

from app.api.schemas.documents import DocumentSummaryOut, EvidenceOut, FlagOut
from app.db import enums
from app.db.models import Document

CONTRACT = Path(__file__).resolve().parents[3] / "contracts" / "openapi.yaml"


@pytest.fixture(scope="module")
def schemas() -> dict[str, Any]:
    return yaml.safe_load(CONTRACT.read_text(encoding="utf-8"))["components"]["schemas"]


@pytest.mark.parametrize(
    ("contract_name", "enum_cls"),
    [
        ("Role", enums.Role),
        ("Pillar", enums.Pillar),
        ("Certainty", enums.Certainty),
        ("ReviewStatus", enums.ReviewStatus),
        ("DocumentStatus", enums.DocumentStatus),
        ("DocumentType", enums.DocumentType),
    ],
)
def test_enum_values_are_the_contracts(
    schemas: dict[str, Any], contract_name: str, enum_cls: type[StrEnum]
) -> None:
    assert [m.value for m in enum_cls] == schemas[contract_name]["enum"]


def test_nested_enum_values_are_the_contracts(schemas: dict[str, Any]) -> None:
    assert [m.value for m in enums.JobStatus] == schemas["Job"]["properties"]["status"]["enum"]
    employment = schemas["CaseProfile"]["properties"]["employment_type"]["enum"]
    assert [m.value for m in enums.EmploymentType] == employment
    assert schemas["Severity"]["enum"] == ["error", "warning", "info"]


def _properties(schema: dict[str, Any]) -> set[str]:
    return set(schema["properties"])


def test_document_summary_uses_the_contracts_names(schemas: dict[str, Any]) -> None:
    contract = _properties(schemas["DocumentSummary"])
    # Every field the API sends is one the contract defines ...
    assert set(DocumentSummaryOut.model_fields) == contract
    # ... and the database names never leak out under their own names.
    sent = set(DocumentSummaryOut.model_json_schema(mode="serialization")["properties"])
    assert sent == contract
    assert (
        not {"borrower", "doc_type_certainty", "created_at", "s3_key", "sha256", "size_bytes"}
        & sent
    )


def test_evidence_and_flag_use_the_contracts_names(schemas: dict[str, Any]) -> None:
    assert set(EvidenceOut.model_fields) == _properties(schemas["Evidence"])
    assert set(FlagOut.model_fields) == _properties(schemas["Flag"])


def test_document_row_is_renamed_for_the_api() -> None:
    now = datetime(2026, 11, 18, tzinfo=UTC)
    row = Document(
        id=uuid.uuid4(),
        case_id=uuid.uuid4(),
        file_name="pay_stub.pdf",
        s3_key="cases/abc/pay_stub.pdf",
        sha256="a" * 64,
        mime="application/pdf",
        size_bytes=2048,
        page_count=2,
        declared_type=None,
        doc_type="pay_stub",
        doc_type_certainty=enums.Certainty.HIGH,
        doc_type_source=enums.DocTypeSource.AI,
        status=enums.DocumentStatus.NEEDS_REVIEW,
        borrower="Daniel Reyes",
        created_at=now,
    )

    body = DocumentSummaryOut.model_validate(row).model_dump(mode="json")

    assert body["owner"] == "Daniel Reyes"
    assert body["type_certainty"] == "high"
    assert body["uploaded_at"] == now.isoformat().replace("+00:00", "Z")
    assert body["flags"] == []  # flags have their own table from D3
    assert "s3_key" not in body and "cases/abc" not in str(body)
    assert set(body) == set(DocumentSummaryOut.model_fields)


def test_evidence_maps_page_no_and_line_refs() -> None:
    document_id = uuid.uuid4()
    evidence = EvidenceOut.from_refs(document_id=document_id, page_no=1, line_refs=["p1-L31"])
    assert evidence.model_dump(mode="json") == {
        "document_id": str(document_id),
        "page": 1,
        "line_ids": ["p1-L31"],
        "bbox": None,
    }


@pytest.mark.parametrize("bad", ["L31", "p1-31", "P1-L31", "p1-L31 "])
def test_evidence_rejects_a_malformed_line_ref(bad: str) -> None:
    with pytest.raises(ValueError, match="line_ids"):
        EvidenceOut.from_refs(document_id=uuid.uuid4(), page_no=1, line_refs=[bad])


def test_evidence_page_starts_at_one() -> None:
    with pytest.raises(ValueError, match="page"):
        EvidenceOut.from_refs(document_id=uuid.uuid4(), page_no=0, line_refs=["p1-L1"])

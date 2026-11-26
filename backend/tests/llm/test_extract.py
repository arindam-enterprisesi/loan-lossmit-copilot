"""extract@1: field schemas, page batches merged in code, line-ID checks (Feature Design 1.5)."""

import json
from typing import Any

import pytest
from pydantic import BaseModel

from app.llm.config import ConfigError, ExtractionSettings
from app.llm.gateway import Gateway
from app.llm.samples import load_lines
from app.llm.smoke import EXPECTED_PAY_STUB
from app.llm.tasks import (
    DocumentLine,
    ExtractionNotSupportedError,
    extract,
    merge_extractions,
    page_batches,
)
from app.llm.types import AdapterResponse
from app.prompts.schemas.documents import PayStubFields
from app.prompts.schemas.fields import (
    ExtractedField,
    Schema,
    Signal,
    extraction_model,
    render_field_list,
    undescribed_fields,
)
from app.prompts.schemas.registry import REGISTRY, DocumentType

from .fakes import FakeAdapter, fake_config

PAY_STUB = load_lines("daniel_pay_stub")
EXTRACTABLE = [t for t, spec in REGISTRY.items() if spec.fields_model is not None]


# ---------- helpers ----------


def fv(value: str | None, *lines: str, certainty: str = "high") -> dict[str, Any]:
    if value is None:
        return {"value": None, "lines": [], "certainty": "low"}
    return {"value": value, "lines": list(lines), "certainty": certainty}


def blank(model: type[BaseModel]) -> dict[str, Any]:
    """A reply with every field null and every repeating group empty."""
    out: dict[str, Any] = {}
    for name, info in model.model_fields.items():
        out[name] = fv(None) if info.annotation is ExtractedField else []
    return out


def daniel_pay_stub_reply() -> dict[str, Any]:
    fields = blank(PayStubFields)
    fields.update(
        employer_name=fv("Cedar Valley Manufacturing, Inc.", "p1-L1"),
        employee_name=fv("Daniel Reyes", "p1-L5"),
        pay_frequency=fv("Biweekly", "p1-L8"),
        pay_period_start=fv("2026-09-14", "p1-L9"),
        pay_period_end=fv("2026-09-27", "p1-L9"),
        pay_date=fv("2026-10-02", "p1-L10"),
        earnings=[
            {
                "description": fv("Regular", "p1-L14"),
                "hours": fv("80.00", "p1-L14"),
                "rate": fv("34.50", "p1-L14"),
                "current": fv("2,760.00", "p1-L14"),
                "ytd": fv("52,440.00", "p1-L14"),
            },
            {
                "description": fv("Overtime 1.5x", "p1-L15"),
                "hours": fv("3.96", "p1-L15"),
                "rate": fv("51.75", "p1-L15"),
                "current": fv("204.93", "p1-L15"),
                "ytd": fv("3,897.10", "p1-L15"),
            },
            {
                "description": fv("Bonus", "p1-L16"),
                "hours": fv(None),
                "rate": fv(None),
                "current": fv("105.57", "p1-L16"),
                "ytd": fv("2,002.40", "p1-L16"),
            },
        ],
        gross_pay_current=fv("3,070.50", "p1-L17", "p1-L27"),
        gross_pay_ytd=fv("58,339.50", "p1-L17", "p1-L29"),
        total_deductions_current=fv("1,036.89", "p1-L25"),
        total_deductions_ytd=fv("19,700.91", "p1-L25"),
        net_pay_current=fv("2,083.61", "p1-L31", certainty="medium"),
        net_pay_ytd=fv("38,638.59", "p1-L32", "p2-L16"),
    )
    return {"fields": fields, "signals": []}


def reply(body: dict[str, Any]) -> AdapterResponse:
    return AdapterResponse(text=json.dumps(body), input_tokens=900, output_tokens=400)


def gateway_for(adapter: FakeAdapter, max_pages: int = 4) -> Gateway:
    settings = ExtractionSettings(max_pages_per_call=max_pages)
    return Gateway({"fake": adapter}, fake_config().model_copy(update={"extraction": settings}))


# ---------- schemas ----------


def _walk_objects(schema: dict[str, Any]) -> list[dict[str, Any]]:
    objects = [schema, *schema.get("$defs", {}).values()]
    return [o for o in objects if o.get("type") == "object"]


@pytest.mark.parametrize("doc_type", EXTRACTABLE, ids=str)
def test_schemas_suit_strict_json_mode(doc_type: DocumentType) -> None:
    """Every property required and no extra keys, so strict provider modes accept it."""
    fields_model = REGISTRY[doc_type].fields_model
    assert fields_model is not None
    schema = extraction_model(fields_model).model_json_schema()
    for obj in _walk_objects(schema):
        assert obj.get("additionalProperties") is False, obj.get("title")
        assert sorted(obj.get("required", [])) == sorted(obj["properties"]), obj.get("title")
        for prop in obj["properties"].values():
            # No keywords next to a $ref (some strict modes reject them).
            if "$ref" in prop:
                assert set(prop) == {"$ref"}, (obj.get("title"), prop)


@pytest.mark.parametrize("doc_type", EXTRACTABLE, ids=str)
def test_every_field_has_guidance_and_a_plain_schema_name(doc_type: DocumentType) -> None:
    fields_model = REGISTRY[doc_type].fields_model
    assert fields_model is not None
    assert undescribed_fields(fields_model) == []
    name = extraction_model(fields_model).__name__
    assert name.replace("_", "").isalnum(), name


def test_classify_only_types_have_no_field_schema() -> None:
    no_schema = {t for t, spec in REGISTRY.items() if spec.fields_model is None}
    assert no_schema == {DocumentType.HARDSHIP_LETTER}


def test_field_list_shows_row_columns() -> None:
    text = render_field_list(PayStubFields)
    assert "- net_pay_current: Net pay for the current period." in text
    assert "- earnings (one entry per row, in document order):" in text
    assert "    - ytd: Year-to-date amount." in text


# ---------- extract ----------


async def test_extract_daniel_pay_stub_in_one_call() -> None:
    adapter = FakeAdapter([reply(daniel_pay_stub_reply())])

    outcome = await extract(PAY_STUB, DocumentType.PAY_STUB, gateway=gateway_for(adapter))

    fields = outcome.result.fields
    assert isinstance(fields, PayStubFields)
    assert fields.net_pay_current.value == "2,083.61"
    assert fields.net_pay_current.lines == ["p1-L31"]
    assert [row.description.value for row in fields.earnings] == [
        "Regular",
        "Overtime 1.5x",
        "Bonus",
    ]
    assert outcome.unknown_line_ids == []
    assert len(outcome.calls) == 1

    request = adapter.requests[0]
    user = request.messages[0].content
    assert "Document type: Pay stub" in user
    assert "These are all 2 page(s) of the document." in user
    assert "p1-L31: Net Pay 2,083.61" in user
    assert "p2-L19: Page 2 of 2" in user
    assert "pay_stub_2026-09-27" not in user  # never the file name
    assert "untrusted data" in (request.system or "")
    assert request.output_model.__name__ == "PayStubFieldsExtraction"


async def test_unknown_line_ids_are_reported() -> None:
    body = daniel_pay_stub_reply()
    body["fields"]["net_pay_current"] = fv("2,083.61", "p1-L99")
    body["signals"] = [{"kind": "other", "detail": "x", "lines": ["p7-L1"]}]
    adapter = FakeAdapter([reply(body)])

    outcome = await extract(PAY_STUB, DocumentType.PAY_STUB, gateway=gateway_for(adapter))

    assert outcome.unknown_line_ids == ["p1-L99", "p7-L1"]


async def test_invalid_reply_is_retried_once_by_the_gateway() -> None:
    bad = daniel_pay_stub_reply()
    del bad["fields"]["net_pay_ytd"]  # a required field omitted
    adapter = FakeAdapter([reply(bad), reply(daniel_pay_stub_reply())])

    outcome = await extract(PAY_STUB, DocumentType.PAY_STUB, gateway=gateway_for(adapter))

    assert outcome.calls[0].attempts == 2
    assert "net_pay_ytd" in adapter.requests[1].messages[-1].content


async def test_long_documents_go_in_page_batches_and_merge() -> None:
    page1 = daniel_pay_stub_reply()
    page2 = {"fields": blank(PayStubFields), "signals": []}
    page2["fields"]["net_pay_ytd"] = fv("38,638.59", "p2-L16")
    page2["fields"]["employee_name"] = fv("Daniel Reyes", "p2-L3")
    page1["fields"]["net_pay_ytd"] = fv("38,638.59", "p1-L32", certainty="medium")
    adapter = FakeAdapter([reply(page1), reply(page2)])

    outcome = await extract(
        PAY_STUB, DocumentType.PAY_STUB, gateway=gateway_for(adapter, max_pages=1)
    )

    assert len(adapter.requests) == 2
    first, second = (r.messages[0].content for r in adapter.requests)
    assert "These are pages 1 to 1 of 2" in first and "p2-L1:" not in first
    assert "These are pages 2 to 2 of 2" in second and "p1-L1:" not in second
    fields = outcome.result.fields
    # Same value on both pages: lines joined, best certainty kept.
    assert fields.net_pay_ytd.lines == ["p1-L32", "p2-L16"]
    assert fields.net_pay_ytd.certainty == "high"
    assert fields.employee_name.lines == ["p1-L5", "p2-L3"]
    assert fields.net_pay_current.value == "2,083.61"  # page 2 had null
    assert len(fields.earnings) == 3
    assert outcome.conflicts == []
    assert outcome.unknown_line_ids == []


async def test_a_page_cited_outside_its_batch_is_unknown() -> None:
    page1 = daniel_pay_stub_reply()
    page1["fields"]["net_pay_ytd"] = fv("38,638.59", "p2-L16")  # page 2 was not sent here
    page2 = {"fields": blank(PayStubFields), "signals": []}
    adapter = FakeAdapter([reply(page1), reply(page2)])

    outcome = await extract(
        PAY_STUB, DocumentType.PAY_STUB, gateway=gateway_for(adapter, max_pages=1)
    )

    assert outcome.unknown_line_ids == ["p2-L16"]


async def test_classify_only_and_unrecognized_types_are_refused() -> None:
    gateway = gateway_for(FakeAdapter([]))
    for doc_type in (
        DocumentType.HARDSHIP_LETTER,
        DocumentType.UNRECOGNIZED,
    ):
        with pytest.raises(ExtractionNotSupportedError):
            await extract(PAY_STUB, doc_type, gateway=gateway)


async def test_extract_needs_the_extraction_config() -> None:
    gateway = Gateway({"fake": FakeAdapter([])}, fake_config())
    with pytest.raises(ConfigError, match="extraction"):
        await extract(PAY_STUB, DocumentType.PAY_STUB, gateway=gateway)


# ---------- merge in code ----------


def _result(**fields: Any) -> Any:
    model = extraction_model(PayStubFields)
    body = blank(PayStubFields)
    body.update(fields)
    return model.model_validate({"fields": body, "signals": []})


def test_merge_keeps_the_first_value_and_reports_a_conflict() -> None:
    a = _result(net_pay_current=fv("2,083.61", "p1-L31"))
    b = _result(net_pay_current=fv("2,033.61", "p5-L2"))

    merged, conflicts = merge_extractions([a, b])

    assert merged.fields.net_pay_current.value == "2,083.61"
    assert merged.fields.net_pay_current.lines == ["p1-L31"]
    assert merged.fields.net_pay_current.certainty == "low"
    assert [(c.field, c.lines) for c in conflicts] == [("net_pay_current", ["p1-L31", "p5-L2"])]


def test_merge_joins_rows_and_signals_in_page_order() -> None:
    row = {
        "description": fv("Federal income tax", "p1-L19"),
        "current": fv("428.30", "p1-L19"),
        "ytd": fv("8,137.70", "p1-L19"),
    }
    later = {**row, "description": fv("Medicare", "p5-L1")}
    a = _result(deductions=[row])
    b = _result(deductions=[later])
    b.signals.append(Signal(kind="cut_off_table", detail="rows stop", lines=["p5-L9"]))

    merged, conflicts = merge_extractions([a, b])

    assert [r.description.value for r in merged.fields.deductions] == [
        "Federal income tax",
        "Medicare",
    ]
    assert [s.kind for s in merged.signals] == ["cut_off_table"]
    assert conflicts == []


def test_merge_treats_whitespace_differences_as_the_same_value() -> None:
    a = _result(employer_name=fv("Cedar Valley  Manufacturing, Inc.", "p1-L1"))
    b = _result(employer_name=fv("Cedar Valley Manufacturing, Inc.", "p2-L1"))
    merged, conflicts = merge_extractions([a, b])
    assert conflicts == []
    assert merged.fields.employer_name.lines == ["p1-L1", "p2-L1"]


def test_page_batches_follow_page_order() -> None:
    lines = [DocumentLine(p, 1, f"page {p}") for p in (3, 1, 2, 5, 4)]
    batches = page_batches(lines, 2)
    assert [sorted({ln.page for ln in b}) for b in batches] == [[1, 2], [3, 4], [5]]


def test_merge_needs_at_least_one_batch() -> None:
    with pytest.raises(ValueError):
        merge_extractions([])


def test_schema_base_forbids_extra_keys() -> None:
    class Probe(Schema):
        a: ExtractedField

    with pytest.raises(ValueError):
        Probe.model_validate({"a": fv("x", "p1-L1"), "b": 1})


def test_smoke_expectations_match_the_sample_lines() -> None:
    text = {ln.line_id: ln.text for ln in PAY_STUB}
    for name, (value, line) in EXPECTED_PAY_STUB.items():
        assert value in text[line], name
    assert text["p1-L31"] == "Net Pay 2,083.61"  # the deliberate misprint (true net 2,033.61)

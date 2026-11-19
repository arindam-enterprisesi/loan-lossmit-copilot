"""hardship@1: Angela Whitfield's letter read into a profile, quotes checked in code (FD 7.5)."""

import json
from typing import Any

import pytest

from app.llm.gateway import Gateway
from app.llm.hardship import read_hardship_letter
from app.llm.samples import load_lines
from app.llm.types import AdapterResponse
from app.prompts.schemas.hardship import (
    HardshipConfig,
    hardship_profile_model,
    load_hardship_config,
)

from .fakes import FakeAdapter, fake_config

LETTER = load_lines("angela_hardship_letter")
APPLICATION_REASONS = ["Reduction in income"]


def q(quote: str | None, *lines: str, **extra: object) -> dict[str, Any]:
    return {"quote": quote, "lines": list(lines), **extra}


def angela_reply() -> dict[str, Any]:
    """What a correct reading of Angela's letter looks like (FD 7.8 example)."""
    return {
        "primary_reason": q(
            "cut my hours from 40 to 30 a week in July",
            "p1-L6",
            category="reduction_in_income",
            financial_effect="hours and pay reduced by a quarter",
        ),
        "other_reasons": [],
        "onset": q("in July", "p1-L6", as_stated="July", month="2026-07"),
        "duration": q(
            "I do not know whether my hours will return to 40 a week", "p1-L9", category="unknown"
        ),
        "intent": q("I want to keep my home", "p1-L14", category="keep"),
        "timeline": [
            q(
                "my employer cut my hours from 40 to 30 a week in July",
                "p1-L6",
                when="July",
                event="Working hours reduced from 40 to 30 a week",
            ),
            q("I fell behind in August", "p1-L7", when="August", event="Fell behind on payments"),
        ],
        "enclosed_documents": [
            q("my application", "p1-L11", document="Mortgage assistance application"),
            q("my recent pay stubs", "p1-L11", document="Pay stubs"),
            q("my recent bank statements", "p1-L11", document="Bank statements"),
        ],
    }


def reply(body: dict[str, Any]) -> AdapterResponse:
    return AdapterResponse(text=json.dumps(body), input_tokens=700, output_tokens=500)


async def test_angela_letter_profile_and_quotes() -> None:
    """D4: reduction_in_income, onset July 2026, duration unknown, intent keep, all verified."""
    adapter = FakeAdapter([reply(angela_reply())])

    outcome = await read_hardship_letter(
        LETTER,
        application_reasons=APPLICATION_REASONS,
        gateway=Gateway({"fake": adapter}, fake_config()),
    )

    p = outcome.profile
    assert p.primary_reason.category == "reduction_in_income"
    assert p.onset.month == "2026-07"
    assert p.duration.category == "unknown"
    assert p.intent.category == "keep"
    assert outcome.all_quotes_verified, outcome.flagged
    assert len(outcome.quote_checks) == 9
    assert outcome.unknown_line_ids == []
    assert outcome.config_version == load_hardship_config().version


async def test_prompt_carries_categories_reasons_and_rules() -> None:
    adapter = FakeAdapter([reply(angela_reply())])
    await read_hardship_letter(
        LETTER,
        application_reasons=APPLICATION_REASONS,
        gateway=Gateway({"fake": adapter}, fake_config()),
    )

    request = adapter.requests[0]
    system, user = request.system or "", request.messages[0].content
    assert "untrusted data" in system
    assert "at most 160 characters" in system
    assert "Do not judge whether the borrower is credible" in system
    assert "- medical_or_disability: Medical or disability (sensitive)" in user
    assert "- reduction_in_income: Reduction in income\n" in user
    assert "Reasons ticked on the application:\n- Reduction in income" in user
    assert "p1-L6: Because my employer cut my hours from 40 to 30 a week in July" in user
    schema = request.output_model.model_json_schema()
    enum = schema["$defs"]["HardshipReason"]["properties"]["category"]["enum"]
    assert enum == list(load_hardship_config().keys)


async def test_a_category_outside_the_list_is_retried() -> None:
    bad = angela_reply()
    bad["primary_reason"]["category"] = "job_loss"
    adapter = FakeAdapter([reply(bad), reply(angela_reply())])

    outcome = await read_hardship_letter(LETTER, gateway=Gateway({"fake": adapter}, fake_config()))

    assert outcome.call.attempts == 2
    assert "primary_reason.category" in adapter.requests[1].messages[-1].content
    assert "(none ticked)" in adapter.requests[0].messages[0].content


async def test_unverified_quotes_are_flagged_not_dropped() -> None:
    body = angela_reply()
    body["intent"] = q("I really want to keep my house", "p1-L14", category="keep")
    body["timeline"][1]["lines"] = ["p1-L7", "p2-L1"]  # no page 2 in this letter
    adapter = FakeAdapter([reply(body)])

    outcome = await read_hardship_letter(LETTER, gateway=Gateway({"fake": adapter}, fake_config()))

    assert not outcome.all_quotes_verified
    assert [c.path for c in outcome.flagged] == ["intent", "timeline[1]"]
    assert outcome.unknown_line_ids == ["p2-L1"]
    assert outcome.profile.intent.category == "keep"  # kept for a person to review


def test_repo_config_has_the_feature_design_categories() -> None:
    config = load_hardship_config()
    assert config.label == "illustrative"
    assert config.keys == (
        "reduction_in_income",
        "unemployment",
        "increase_in_housing_expense",
        "medical_or_disability",
        "divorce_or_separation",
        "death_in_household",
        "disaster",
        "business_failure",
        "other",
    )
    sensitive = {c.key for c in config.categories if c.sensitive}
    assert sensitive == {"medical_or_disability", "divorce_or_separation", "death_in_household"}


@pytest.mark.parametrize(
    "categories",
    [
        [{"key": "other", "label": "Other"}, {"key": "other", "label": "Again"}],
        [{"key": "unemployment", "label": "Unemployment"}],
    ],
    ids=["duplicate", "no-other"],
)
def test_config_rejects_duplicates_and_a_missing_other(categories: list[dict[str, str]]) -> None:
    with pytest.raises(ValueError):
        HardshipConfig.model_validate(
            {
                "version": "t",
                "label": "illustrative",
                "categories": categories,
                "max_quote_chars": 9,
            }
        )


def test_profile_model_is_strict_and_plainly_named() -> None:
    model = hardship_profile_model(load_hardship_config().keys)
    schema = model.model_json_schema()
    assert model.__name__ == "HardshipProfileResult"
    for obj in [schema, *schema["$defs"].values()]:
        if obj.get("type") == "object":
            assert obj["additionalProperties"] is False
            assert sorted(obj["required"]) == sorted(obj["properties"])

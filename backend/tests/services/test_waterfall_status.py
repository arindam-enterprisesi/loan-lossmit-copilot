"""The waterfall's status rule: conditions to options, overrides, and "no earlier option met".

Pure code. The seeded sample for Angela is checked against the same rule, so the data file and the
rule the rules engine will use cannot drift apart.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.services.waterfall_status import effective_status, option_status, recompute

SEED = Path(__file__).resolve().parents[2] / "app" / "db" / "demo" / "angela_lm_recommendation.json"


def cond(status: str, *, override: str | None = None, derived: bool = False) -> dict[str, Any]:
    out: dict[str, Any] = {"id": "x", "status": status, "derived": derived}
    if override:
        out["override"] = {"status": override, "reason": "r", "by": "u", "at": "t"}
    return out


def test_every_condition_must_be_met_for_the_option_to_be_met() -> None:
    assert option_status([cond("met"), cond("met")]) == "met"
    assert option_status([cond("met"), cond("not_met")]) == "not_met"


def test_not_met_outranks_needs_confirmation_which_outranks_not_evaluable() -> None:
    assert option_status([cond("needs_confirmation"), cond("not_met")]) == "not_met"
    assert (
        option_status([cond("not_evaluable"), cond("needs_confirmation")]) == "needs_confirmation"
    )
    assert option_status([cond("met"), cond("not_evaluable")]) == "not_evaluable"


def test_an_option_with_no_conditions_cannot_be_evaluated() -> None:
    assert option_status([]) == "not_evaluable"


def test_an_override_counts_in_place_of_the_rules_status() -> None:
    assert effective_status(cond("not_met", override="met")) == "met"
    assert option_status([cond("not_met", override="met"), cond("met")]) == "met"


def test_the_waterfall_stops_at_the_first_option_that_is_met() -> None:
    plan = recompute([[cond("not_met")], [cond("met")], [cond("met")], [cond("not_met")]])

    assert [status for status, _ in plan] == ["not_met", "met", "not_reached", "not_reached"]


def test_a_derived_condition_follows_the_options_before_it() -> None:
    later = [cond("not_reached", derived=True), cond("not_evaluable")]

    unmet = recompute([[cond("not_met")], later])
    met = recompute([[cond("met")], later])

    assert unmet[1][1][0]["status"] == "met" and unmet[1][0] == "not_evaluable"
    assert met[1][1][0]["status"] == "not_reached" and met[1][0] == "not_reached"


def test_recomputing_never_changes_what_it_was_given() -> None:
    given = [[cond("not_met")], [cond("not_reached", derived=True)]]
    before = json.dumps(given)

    recompute(given)

    assert json.dumps(given) == before


def test_the_seeded_waterfall_is_what_the_rule_gives_its_own_conditions() -> None:
    options = json.loads(SEED.read_text(encoding="utf-8"))["options"]

    plan = recompute([o["conditions"] for o in options])

    assert [s for s, _ in plan] == [o["status"] for o in options]
    assert [c for _, c in plan] == [o["conditions"] for o in options]
    assert [o["status"] for o in options] == [
        "not_met",
        "not_met",
        "not_met",
        "met",
        "not_reached",
        "not_reached",
    ]

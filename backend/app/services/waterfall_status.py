"""Turn each condition's status into each option's status (Feature Design 8.3, 8.4 and 8.2 step 5).

Pure code over plain dicts, so the rules engine and a reviewer's override share one rule:

* a condition's *effective* status is the reviewer's override when there is one, else the rules';
* an option is ``not_reached`` when an earlier option's conditions are met (the waterfall stops at
  the first one), or when one of its own conditions is ``not_reached``;
* otherwise ``not_met`` if any condition is not met, then ``needs_confirmation`` if a judgement is
  not yet confirmed, then ``not_evaluable`` if a condition cannot be computed, and ``met`` only if
  every condition is met (an option with no conditions is not evaluable);
* a *derived* condition (``derived: true``: "no earlier option's conditions are met") is set here
  from the options before it, never by a person.

``met`` says the conditions are met and nothing more: it is not an offer or a decision (rule 3).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from app.db.enums import WaterfallStatus

Condition = dict[str, Any]
MET, NOT_MET = WaterfallStatus.MET.value, WaterfallStatus.NOT_MET.value
NOT_REACHED = WaterfallStatus.NOT_REACHED.value
NEEDS_CONFIRMATION = WaterfallStatus.NEEDS_CONFIRMATION.value
NOT_EVALUABLE = WaterfallStatus.NOT_EVALUABLE.value


def effective_status(condition: Mapping[str, Any]) -> str:
    override = condition.get("override")
    return str(override["status"]) if override else str(condition["status"])


def option_status(conditions: Sequence[Mapping[str, Any]]) -> str:
    """The status of one option that the waterfall has reached."""
    statuses = [effective_status(c) for c in conditions]
    if NOT_REACHED in statuses:
        return NOT_REACHED
    for wanted in (NOT_MET, NEEDS_CONFIRMATION, NOT_EVALUABLE):
        if wanted in statuses:
            return wanted
    return MET if statuses else NOT_EVALUABLE


def recompute(options: Sequence[Sequence[Condition]]) -> list[tuple[str, list[Condition]]]:
    """Statuses for options in waterfall order. Returns (option status, conditions) for each, with
    the derived conditions brought up to date. Conditions are copied, never changed in place."""
    out: list[tuple[str, list[Condition]]] = []
    earlier_met = False
    for conditions in options:
        updated = [dict(c) for c in conditions]
        for c in updated:
            if c.get("derived"):
                c["status"] = NOT_REACHED if earlier_met else MET
        status = NOT_REACHED if earlier_met else option_status(updated)
        out.append((status, updated))
        earlier_met = earlier_met or status == MET
    return out

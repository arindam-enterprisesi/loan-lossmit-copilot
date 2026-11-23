"""Reviewing the reports through the API: conditions, the waterfall override, sign-off and the audit
trail (Feature Design 6.7, 6.8, 8.2 and 8.7).

The reports are the seeded samples (no model, no rules engine yet). The Daniel story is the
Feature Design's: six suggested conditions, five accepted, one rejected with the reason
"not required for this file", then the review is signed off. Nothing a person does may
overwrite what the system wrote, every action is audited, and only the right role may act:
the underwriter on Pillar 1, the loss mitigation specialist on Pillar 2, and the administrator
on neither.
"""

from __future__ import annotations

import json
import re
import uuid
from typing import Any

import httpx
import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.demo.reports import seed_lm_recommendation, seed_underwriting_report
from app.db.enums import Role
from app.db.seed import case_id, seed
from tests.db.conftest import auth_headers

DANIEL = case_id("Daniel Reyes — purchase")
ANGELA = case_id("Angela Whitfield — hardship")
UW = f"/api/v1/cases/{DANIEL}/underwriting-report"
LM = f"/api/v1/cases/{ANGELA}/lm-recommendation"
BLOCKED = re.compile(r"\b(approve[sd]?|deny|denied|offer(s|ed)?|eligible|qualifies)\b", re.I)
REJECTION = "not required for this file"


@pytest.fixture(autouse=True)
async def seeded(session: AsyncSession) -> None:
    await seed(session, "demo-pass")
    await seed_underwriting_report(session, DANIEL)
    await seed_lm_recommendation(session, ANGELA)
    await session.flush()


def headers(role: Role = Role.UNDERWRITER) -> dict[str, str]:
    return auth_headers(role)


def lm_headers() -> dict[str, str]:
    return headers(Role.LM_SPECIALIST)


async def report(client: httpx.AsyncClient) -> dict[str, Any]:
    response = await client.get(f"{UW}/latest", headers=headers())
    assert response.status_code == 200, response.text
    return response.json()  # type: ignore[no-any-return]


async def waterfall(client: httpx.AsyncClient) -> dict[str, Any]:
    response = await client.get(f"{LM}/latest", headers=lm_headers())
    assert response.status_code == 200, response.text
    return response.json()  # type: ignore[no-any-return]


def option(view: dict[str, Any], name: str) -> dict[str, Any]:
    return next(o for o in view["waterfall"] if o["option"] == name)


def statuses(view: dict[str, Any]) -> list[str]:
    return [o["status"] for o in view["waterfall"]]


async def decide(
    client: httpx.AsyncClient, condition: str, body: dict[str, Any], role: Role = Role.UNDERWRITER
) -> httpx.Response:
    return await client.patch(
        f"{UW}/latest/conditions/{condition}", json=body, headers=headers(role)
    )


async def override(
    client: httpx.AsyncClient, condition: str, status: str, reason: str = "Specialist's judgement."
) -> httpx.Response:
    return await client.put(
        f"{LM}/latest/conditions/{condition}/override",
        json={"status": status, "reason": reason},
        headers=lm_headers(),
    )


async def rows(session: AsyncSession, sql: str, **params: Any) -> list[Any]:
    return list((await session.execute(sa.text(sql), params)).all())


async def audit_event(session: AsyncSession, action: str) -> Any:
    """The first audit event of an action: its before, after and reason."""
    found = await rows(
        session,
        "SELECT before, after, reason FROM audit_events WHERE action = :a ORDER BY id",
        a=action,
    )
    return found[0]


# --- reading the seeded underwriting report --------------------------------------------------


async def test_the_seeded_report_is_labelled_and_has_findings_six_conditions_and_a_run_log(
    client: httpx.AsyncClient,
) -> None:
    view = await report(client)

    assert view["report"]["source"] == "seeded_sample"
    assert view["report"]["notice"].startswith("Seeded sample")
    assert (view["report"]["kind"], view["report"]["status"], view["report"]["version"]) == (
        "underwriting",
        "draft",
        1,
    )
    assert len(view["findings"]) == 8
    assert [f["priority"] for f in view["findings"]][:3] == ["significant"] * 3
    assert all(f["evidence"] for f in view["findings"])  # every finding links to evidence (rule 2)
    assert len(view["conditions"]) == 6
    assert {c["decision"] for c in view["conditions"]} == {"pending"}
    assert [c["position"] for c in view["conditions"]] == [1, 2, 3, 4, 5, 6]
    assert [a["agent"] for a in view["agent_runs"]] == ["researcher", "writer", "critic"]
    assert {a["provider"] for a in view["agent_runs"]} == {"seeded_sample"}
    assert view["sign_offs"] == []
    sections = view["report"]["sections"]
    assert "41.61%" in sections["conflicts"][0]["detail"]  # the DTI conflict is shown openly


async def test_the_seeded_report_is_not_seeded_twice(session: AsyncSession) -> None:
    again = await seed_underwriting_report(session, DANIEL)

    assert again.version == 1
    count = (await rows(session, "SELECT count(*) FROM reports WHERE kind = 'underwriting'"))[0][0]
    assert count == 1


# --- the Feature Design's story --------------------------------------------------------------


async def test_the_underwriter_accepts_five_rejects_one_and_signs_off(
    client: httpx.AsyncClient, session: AsyncSession
) -> None:
    view = await report(client)
    ids = [c["id"] for c in view["conditions"]]

    for condition in ids[:5]:
        response = await decide(client, condition, {"decision": "accepted"})
        assert response.status_code == 200, response.text
    rejected = await decide(client, ids[5], {"decision": "rejected", "reason": REJECTION})
    assert rejected.status_code == 200

    after = rejected.json()
    assert [c["decision"] for c in after["conditions"]] == ["accepted"] * 5 + ["rejected"]
    assert after["conditions"][5]["reason"] == REJECTION
    assert all(c["decided_by"] and c["decided_at"] for c in after["conditions"])
    assert after["report"]["status"] == "in_review"

    signed = await client.post(
        f"{UW}/latest/sign-off", json={"note": "Reviewed."}, headers=headers()
    )
    assert signed.status_code == 201, signed.text
    result = signed.json()
    assert result["sign_off"]["statement"] == "Records a review. Not a decision."
    assert (result["report_status"], result["pending_conditions"]) == ("signed_off", 0)
    assert (result["sign_off"]["role"], result["sign_off"]["report_version"]) == ("underwriter", 1)
    final = await report(client)
    assert final["report"]["status"] == "signed_off" and len(final["sign_offs"]) == 1

    events = await rows(session, "SELECT action FROM audit_events ORDER BY id")
    actions = [e.action for e in events if e.action.startswith(("underwriting.", "report."))]
    assert actions == ["underwriting.condition_accepted"] * 5 + [
        "underwriting.condition_rejected",
        "report.signed_off",
    ]


async def test_an_edit_keeps_the_agents_text_beside_the_reviewers(
    client: httpx.AsyncClient, session: AsyncSession
) -> None:
    first = (await report(client))["conditions"][0]

    response = await decide(
        client,
        first["id"],
        {
            "decision": "edited",
            "edited_text": "Provide the donor's gift letter for the 2,000.00 transfer.",
            "reason": "The bank record alone is not enough.",
        },
    )

    edited = response.json()["conditions"][0]
    assert edited["text"] == first["text"]  # the agents' words are never changed
    assert edited["edited_text"].startswith("Provide the donor's gift letter")
    assert edited["current_text"] == edited["edited_text"]
    assert edited["decision"] == "edited" and edited["reason"].startswith("The bank record")
    stored = (
        await rows(session, "SELECT text, edited_text FROM conditions WHERE id = :i", i=first["id"])
    )[0]
    assert stored.text == first["text"] and stored.edited_text == edited["edited_text"]
    event = await audit_event(session, "underwriting.condition_edited")
    assert event.before["decision"] == "pending"
    assert event.after["original_text"] == first["text"]
    assert event.reason.startswith("The bank record")


async def test_changing_your_mind_keeps_the_earlier_decision_in_the_audit_trail(
    client: httpx.AsyncClient, session: AsyncSession
) -> None:
    condition = (await report(client))["conditions"][2]["id"]
    await decide(client, condition, {"decision": "rejected", "reason": "Already on file."})

    response = await decide(client, condition, {"decision": "accepted"})

    changed = response.json()["conditions"][2]
    assert changed["decision"] == "accepted" and changed["reason"] is None
    last = await audit_event(session, "underwriting.condition_accepted")
    assert last.before["decision"] == "rejected" and last.before["reason"] == "Already on file."


async def test_the_underwriter_can_add_a_condition_of_their_own(client: httpx.AsyncClient) -> None:
    response = await client.post(
        f"{UW}/latest/conditions",
        json={"text": "  Provide the signed purchase contract.  ", "priority": "significant"},
        headers=headers(),
    )

    assert response.status_code == 201, response.text
    added = response.json()["conditions"][-1]
    assert (added["source"], added["decision"], added["position"]) == ("user", "accepted", 7)
    assert added["text"] == "Provide the signed purchase contract."
    assert added["decided_by"] is not None
    assert len(response.json()["conditions"]) == 7


async def test_a_review_needs_the_right_words(
    client: httpx.AsyncClient, session: AsyncSession
) -> None:
    condition = (await report(client))["conditions"][0]["id"]

    for body in (
        {"decision": "rejected"},
        {"decision": "rejected", "reason": "   "},
        {"decision": "edited", "reason": "why"},
        {"decision": "edited", "edited_text": "new"},
        {"decision": "accepted", "edited_text": "new"},
        {"decision": "pending"},
        {"decision": "approved"},
        {"decision": "accepted", "reason": "x" * 501},
        {"decision": "accepted", "extra": 1},
        {},
    ):
        assert (await decide(client, condition, body)).status_code == 422, body
    for body in (
        {"text": "   "},
        {"text": ""},
        {"text": "x", "priority": "urgent"},
        {"text": "x", "extra": 1},
    ):
        added = await client.post(f"{UW}/latest/conditions", json=body, headers=headers())
        assert added.status_code == 422, body
    assert (
        await rows(session, "SELECT id FROM audit_events WHERE action LIKE 'underwriting.%'")
    ) == []
    assert (await report(client))["report"]["status"] == "draft"


async def test_a_condition_that_is_not_there_is_a_404_and_an_older_report_is_a_409(
    client: httpx.AsyncClient, session: AsyncSession
) -> None:
    old = (await report(client))["conditions"][0]["id"]
    for missing in (str(uuid.uuid4()), "nope"):
        assert (await decide(client, missing, {"decision": "accepted"})).status_code == 404

    # A newer report replaces it: the older one's conditions can no longer be changed.
    run = (
        await session.execute(
            sa.text(
                "INSERT INTO analysis_runs (case_id, feature, status, started_at) "
                "VALUES (:c, 'underwriting', 'succeeded', now() + interval '1 hour') RETURNING id"
            ),
            {"c": DANIEL},
        )
    ).scalar_one()
    await session.execute(
        sa.text(
            "INSERT INTO reports (run_id, case_id, kind, version, source) "
            "VALUES (:r, :c, 'underwriting', 1, 'agents')"
        ),
        {"r": run, "c": DANIEL},
    )
    stale = await decide(client, old, {"decision": "accepted"})

    assert (stale.status_code, stale.json()["code"]) == (409, "stale_report")
    assert (await report(client))["report"]["source"] == "agents"


# --- sign-off --------------------------------------------------------------------------------


async def test_a_sign_off_with_undecided_conditions_says_how_many_and_is_still_only_a_record(
    client: httpx.AsyncClient, session: AsyncSession
) -> None:
    response = await client.post(f"{UW}/latest/sign-off", json={}, headers=headers())

    assert response.status_code == 201
    assert response.json()["pending_conditions"] == 6
    event = await audit_event(session, "report.signed_off")
    assert event.after["statement"] == "Records a review. Not a decision."
    assert event.after["conditions"] == {"pending": 6}


async def test_a_review_is_recorded_once_per_person_and_version_and_a_change_reopens_it(
    client: httpx.AsyncClient,
) -> None:
    await client.post(f"{UW}/latest/sign-off", json={}, headers=headers())

    again = await client.post(f"{UW}/latest/sign-off", json={}, headers=headers())
    assert (again.status_code, again.json()["code"]) == (409, "already_signed_off")

    condition = (await report(client))["conditions"][0]["id"]
    reopened = await decide(client, condition, {"decision": "accepted"})
    assert reopened.json()["report"]["status"] == "in_review"
    assert len(reopened.json()["sign_offs"]) == 1  # the earlier record stays


async def test_a_note_on_the_sign_off_is_kept(client: httpx.AsyncClient) -> None:
    response = await client.post(
        f"{UW}/latest/sign-off", json={"note": "  Checked the DTI conflict.  "}, headers=headers()
    )

    assert response.json()["sign_off"]["note"] == "Checked the DTI conflict."
    assert (
        await client.post(f"{UW}/latest/sign-off", json={"note": "x" * 501}, headers=headers())
    ).status_code == 422


# --- the loss mitigation waterfall -----------------------------------------------------------


async def test_the_seeded_waterfall_and_lender_view_are_angelas_figures(
    client: httpx.AsyncClient,
) -> None:
    view = await waterfall(client)

    assert view["source"] == "seeded_sample" and view["notice"].startswith("Seeded sample")
    assert view["rule_set"] == {
        "name": "Sample Investor A",
        "version": "1",
        "label": "illustrative",
        "banner": "Illustrative: not an actual investor's requirements.",
    }
    assert [o["option"] for o in view["waterfall"]] == [
        "repayment_plan",
        "forbearance",
        "payment_deferral",
        "loan_modification",
        "short_sale",
        "deed_in_lieu",
    ]
    assert statuses(view) == ["not_met", "not_met", "not_met", "met", "not_reached", "not_reached"]
    modification = option(view, "loan_modification")["conditions"]
    target = next(c for c in modification if c["id"].endswith("target_payment"))
    assert target["values"] == {
        "gross_monthly_income": "4200.00",
        "target_payment": "1470.00",
        "contractual_payment": "1720.00",
    }
    assert all(c["passage_id"] for o in view["waterfall"] for c in o["conditions"])  # rule 2
    lender = view["lender_view"]
    assert (lender["foreclosure_loss"], lender["modification_cost"], lender["advantage"]) == (
        "16310.00",
        "13893.00",
        "2417.00",
    )
    assert all(f["working"] and f["formula"] for f in lender["figures"])
    assert lender["figures"][0]["working"] == "212,400.00 + 5,160.00 = 217,560.00"
    assert "to be calculated under the investor's own method" in lender["final_terms"]
    assert view["report"]["report"]["kind"] == "lm_recommendation"
    assert view["report"]["report"]["source"] == "seeded_sample"


async def test_overriding_a_condition_recomputes_the_statuses_and_keeps_the_rules_answer(
    client: httpx.AsyncClient, session: AsyncSession
) -> None:
    response = await override(
        client,
        "loan_modification.target_payment",
        "not_met",
        "Income documents are not yet verified.",
    )

    assert response.status_code == 200, response.text
    view = response.json()
    modification = option(view, "loan_modification")
    assert (modification["status"], modification["original_status"]) == ("not_met", "met")
    assert modification["overridden"] is True
    assert modification["override_reason"] == "Income documents are not yet verified."
    changed = next(c for c in modification["conditions"] if c["id"].endswith("target_payment"))
    assert (changed["status"], changed["effective_status"]) == ("met", "not_met")
    assert changed["override"]["reason"] == "Income documents are not yet verified."
    # Nothing earlier is met any more, so the later options are reached (and cannot be evaluated).
    assert statuses(view)[4:] == ["not_evaluable", "not_evaluable"]
    assert option(view, "short_sale")["original_status"] == "not_reached"
    assert option(view, "short_sale")["overridden"] is False
    assert view["report"]["report"]["status"] == "in_review"
    event = await audit_event(session, "lm.condition_overridden")
    assert event.before["status"] == "met" and event.after["status"] == "not_met"
    assert event.after["option_system_status"] == "met"
    assert event.reason == "Income documents are not yet verified."


async def test_an_override_stays_visible_on_the_next_read(client: httpx.AsyncClient) -> None:
    await override(client, "loan_modification.intent", "needs_confirmation")

    view = await waterfall(client)

    assert option(view, "loan_modification")["status"] == "needs_confirmation"
    assert option(view, "loan_modification")["overridden"] is True


async def test_overriding_the_conditions_of_an_earlier_option_makes_it_met_and_stops_the_waterfall(
    client: httpx.AsyncClient,
) -> None:
    await override(client, "repayment_plan.hardship_resolved", "met")
    view = (await override(client, "repayment_plan.surplus", "met")).json()

    assert statuses(view) == ["met"] + ["not_reached"] * 5
    modification = option(view, "loan_modification")
    assert (modification["status"], modification["original_status"]) == ("not_reached", "met")
    assert all(c["effective_status"] == c["status"] for c in modification["conditions"])


async def test_choosing_the_rules_own_status_removes_the_override(
    client: httpx.AsyncClient,
) -> None:
    await override(client, "loan_modification.target_payment", "not_met")

    view = (
        await override(client, "loan_modification.target_payment", "met", "Documents verified.")
    ).json()

    assert statuses(view) == ["not_met", "not_met", "not_met", "met", "not_reached", "not_reached"]
    modification = option(view, "loan_modification")
    assert modification["overridden"] is False and modification["override_reason"] is None
    assert all(c["override"] is None for c in modification["conditions"])


async def test_a_second_override_in_one_option_keeps_the_first(client: httpx.AsyncClient) -> None:
    await override(client, "loan_modification.intent", "not_met", "First.")
    view = (
        await override(client, "loan_modification.hardship_long_term", "not_met", "Second.")
    ).json()

    conditions = option(view, "loan_modification")["conditions"]
    assert [c["override"]["reason"] for c in conditions if c["override"]] == ["Second.", "First."][
        ::-1
    ] or {c["override"]["reason"] for c in conditions if c["override"]} == {"First.", "Second."}
    assert option(view, "loan_modification")["override_reason"] == "Second."


async def test_an_override_needs_a_reason_a_real_condition_and_one_the_rules_decide(
    client: httpx.AsyncClient, session: AsyncSession
) -> None:
    target = "loan_modification.target_payment"
    for body in (
        {"status": "not_met"},
        {"status": "not_met", "reason": "  "},
        {"status": "not_reached", "reason": "x"},
        {"status": "approved", "reason": "x"},
        {"status": "not_met", "reason": "x" * 501},
        {"status": "not_met", "reason": "x", "extra": 1},
    ):
        response = await client.put(
            f"{LM}/latest/conditions/{target}/override", json=body, headers=lm_headers()
        )
        assert response.status_code == 422, body
    derived = await override(client, "short_sale.reached", "met")
    assert (derived.status_code, derived.json()["code"]) == (422, "derived_condition")
    assert (await override(client, "no.such_condition", "met")).status_code == 404
    assert (await rows(session, "SELECT id FROM audit_events WHERE action LIKE 'lm.%'")) == []
    assert statuses(await waterfall(client))[3] == "met"


async def test_the_specialist_signs_off_the_recommendation_review(
    client: httpx.AsyncClient,
) -> None:
    await override(client, "loan_modification.target_payment", "not_met")

    response = await client.post(
        f"{LM}/latest/sign-off",
        json={"note": "Added a note to request the August statement."},
        headers=lm_headers(),
    )

    assert response.status_code == 201, response.text
    result = response.json()
    assert result["sign_off"]["statement"] == "Records a review. Not a decision."
    assert (result["report_status"], result["sign_off"]["role"]) == ("signed_off", "lm_specialist")
    assert (await waterfall(client))["report"]["sign_offs"][0]["note"].startswith("Added a note")
    again = await client.post(f"{LM}/latest/sign-off", json={}, headers=lm_headers())
    assert again.status_code == 409


# --- who may act -----------------------------------------------------------------------------


async def test_only_the_underwriter_reviews_the_underwriting_report(
    client: httpx.AsyncClient,
) -> None:
    condition = (await report(client))["conditions"][0]["id"]

    for role in (Role.ADMIN, Role.LM_SPECIALIST):
        assert (await decide(client, condition, {"decision": "accepted"}, role)).status_code == 403
        added = await client.post(
            f"{UW}/latest/conditions", json={"text": "x"}, headers=headers(role)
        )
        assert added.status_code == 403
        assert (
            await client.post(f"{UW}/latest/sign-off", json={}, headers=headers(role))
        ).status_code == 403
    assert (await report(client))["conditions"][0]["decision"] == "pending"
    assert (await report(client))["sign_offs"] == []


async def test_only_the_loss_mitigation_specialist_reviews_the_recommendation(
    client: httpx.AsyncClient,
) -> None:
    for role in (Role.ADMIN, Role.UNDERWRITER):
        denied = await client.put(
            f"{LM}/latest/conditions/loan_modification.intent/override",
            json={"status": "not_met", "reason": "x"},
            headers=headers(role),
        )
        assert denied.status_code == 403
        assert (
            await client.post(f"{LM}/latest/sign-off", json={}, headers=headers(role))
        ).status_code == 403
    assert statuses(await waterfall(client))[3] == "met"


async def test_a_case_of_the_other_pillar_is_a_404_for_reading_and_the_admin_reads_both(
    client: httpx.AsyncClient,
) -> None:
    assert (await client.get(f"{UW}/latest", headers=lm_headers())).status_code == 404
    assert (await client.get(f"{LM}/latest", headers=headers())).status_code == 404
    assert (await client.get(f"{UW}/latest", headers=headers(Role.ADMIN))).status_code == 200
    assert (await client.get(f"{LM}/latest", headers=headers(Role.ADMIN))).status_code == 200
    # The right role on a case it cannot see is a 404, not an error that confirms the case exists.
    wrong = await client.post(
        f"{LM.replace(str(ANGELA), str(DANIEL))}/latest/sign-off", json={}, headers=lm_headers()
    )
    assert wrong.status_code == 404


async def test_no_token_is_a_401_everywhere_and_a_malformed_case_is_a_404(
    client: httpx.AsyncClient,
) -> None:
    condition = (await report(client))["conditions"][0]["id"]

    assert (await client.get(f"{UW}/latest")).status_code == 401
    assert (await client.patch(f"{UW}/latest/conditions/{condition}", json={})).status_code == 401
    assert (await client.post(f"{UW}/latest/sign-off", json={})).status_code == 401
    assert (await client.get(f"{LM}/latest")).status_code == 401
    assert (await client.put(f"{LM}/latest/conditions/x/override", json={})).status_code == 401
    assert (await client.get(f"/api/v1/cases/{DANIEL}/audit")).status_code == 401
    for path in ("underwriting-report/latest", "lm-recommendation/latest", "audit"):
        assert (
            await client.get(f"/api/v1/cases/nope/{path}", headers=headers())
        ).status_code == 404


async def test_a_case_with_no_report_yet_is_a_404_for_reading_reviewing_and_signing(
    client: httpx.AsyncClient, session: AsyncSession
) -> None:
    await session.execute(sa.text("DELETE FROM reports"))

    assert (await client.get(f"{UW}/latest", headers=headers())).status_code == 404
    assert (
        await client.post(f"{UW}/latest/sign-off", json={}, headers=headers())
    ).status_code == 404
    assert (
        await client.post(f"{UW}/latest/conditions", json={"text": "x"}, headers=headers())
    ).status_code == 404


# --- the audit trail -------------------------------------------------------------------------


async def test_the_audit_trail_lists_newest_first_with_who_and_why(
    client: httpx.AsyncClient,
) -> None:
    conditions = (await report(client))["conditions"]
    await decide(client, conditions[0]["id"], {"decision": "accepted"})
    await decide(client, conditions[1]["id"], {"decision": "rejected", "reason": REJECTION})
    await client.post(f"{UW}/latest/sign-off", json={}, headers=headers())

    response = await client.get(f"/api/v1/cases/{DANIEL}/audit", headers=headers())

    assert response.status_code == 200
    page = response.json()
    assert [e["action"] for e in page["items"]] == [
        "report.signed_off",
        "underwriting.condition_rejected",
        "underwriting.condition_accepted",
    ]
    assert page["next_before"] is None
    newest = page["items"][0]
    assert newest["role"] == "underwriter" and newest["actor_name"] and newest["actor_id"]
    assert page["items"][1]["reason"] == REJECTION
    ids = [e["id"] for e in page["items"]]
    assert ids == sorted(ids, reverse=True)


async def test_the_audit_trail_filters_by_action_and_entity_and_pages(
    client: httpx.AsyncClient,
) -> None:
    conditions = (await report(client))["conditions"]
    for c in conditions[:4]:
        await decide(client, c["id"], {"decision": "accepted"})
    await decide(client, conditions[4]["id"], {"decision": "rejected", "reason": REJECTION})
    url = f"/api/v1/cases/{DANIEL}/audit"

    by_action = (
        await client.get(
            url, params={"action": "underwriting.condition_rejected"}, headers=headers()
        )
    ).json()
    assert [e["entity_id"] for e in by_action["items"]] == [conditions[4]["id"]]
    by_entity = (
        await client.get(url, params={"entity_type": "condition"}, headers=headers())
    ).json()
    assert len(by_entity["items"]) == 5
    assert (await client.get(url, params={"entity_type": "report"}, headers=headers())).json()[
        "items"
    ] == []

    first = (await client.get(url, params={"limit": 2}, headers=headers())).json()
    assert len(first["items"]) == 2 and first["next_before"] == first["items"][-1]["id"]
    second = (
        await client.get(
            url, params={"limit": 2, "before": first["next_before"]}, headers=headers()
        )
    ).json()
    third = (
        await client.get(
            url, params={"limit": 2, "before": second["next_before"]}, headers=headers()
        )
    ).json()
    seen = [e["id"] for p in (first, second, third) for e in p["items"]]
    assert len(seen) == len(set(seen)) == 5 and third["next_before"] is None
    for bad in ({"limit": 0}, {"limit": 201}, {"before": 0}):
        assert (await client.get(url, params=bad, headers=headers())).status_code == 422


async def test_the_audit_trail_is_only_for_cases_the_caller_can_see(
    client: httpx.AsyncClient,
) -> None:
    url = f"/api/v1/cases/{DANIEL}/audit"

    assert (await client.get(url, headers=lm_headers())).status_code == 404
    assert (await client.get(url, headers=headers(Role.ADMIN))).status_code == 200


async def test_an_override_is_in_the_specialists_audit_trail(client: httpx.AsyncClient) -> None:
    await override(client, "loan_modification.target_payment", "not_met", "Documents not verified.")

    page = (await client.get(f"/api/v1/cases/{ANGELA}/audit", headers=lm_headers())).json()

    event = page["items"][0]
    assert (event["action"], event["entity_type"]) == (
        "lm.condition_overridden",
        "waterfall_condition",
    )
    assert event["reason"] == "Documents not verified."
    assert event["before"]["status"] == "met" and event["after"]["status"] == "not_met"


# --- wording ---------------------------------------------------------------------------------


async def test_no_text_in_any_response_says_approve_deny_offer_eligible_or_qualifies(
    client: httpx.AsyncClient,
) -> None:
    condition = (await report(client))["conditions"][0]["id"]
    await decide(client, condition, {"decision": "accepted"})
    signed = await client.post(f"{UW}/latest/sign-off", json={}, headers=headers())
    overridden = await override(client, "loan_modification.intent", "not_met")
    audit = await client.get(f"/api/v1/cases/{DANIEL}/audit", headers=headers())

    for response in (
        await client.get(f"{UW}/latest", headers=headers()),
        signed,
        await client.get(f"{LM}/latest", headers=lm_headers()),
        overridden,
        audit,
    ):
        texts = re.findall(r'"([^"]+)"', json.dumps(response.json()))
        assert texts and not [t for t in texts if BLOCKED.search(t)]

"""The flags table (migration 0003): its columns, closed value sets and uniqueness."""

from __future__ import annotations

import uuid

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncConnection

from tests.db.conftest import expect_db_error

INSERT = (
    "INSERT INTO flags (case_id, feature, entity_type, entity_id, code, severity, message) "
    "VALUES (:c, 'documents', :t, :e, :code, :s, 'm')"
)


async def _flag(
    conn: AsyncConnection,
    case_id: uuid.UUID,
    entity_id: uuid.UUID,
    code: str = "DI-CHK-02",
    *,
    entity_type: str = "field",
    severity: str = "warning",
) -> None:
    await conn.execute(
        sa.text(INSERT),
        {"c": case_id, "t": entity_type, "e": entity_id, "code": code, "s": severity},
    )


async def test_flags_has_the_schema_docs_columns(conn: AsyncConnection) -> None:
    rows = await conn.execute(
        sa.text(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_schema = 'public' AND table_name = 'flags'"
        )
    )
    names = {r[0] for r in rows}
    # docs/database-schema.md section 2, plus created_at (the "every row" convention).
    assert names == {
        "id",
        "case_id",
        "feature",
        "entity_type",
        "entity_id",
        "code",
        "severity",
        "message",
        "evidence",
        "status",
        "resolved_by",
        "reason",
        "created_at",
    }


async def test_a_new_flag_is_open_and_unresolved(conn: AsyncConnection, case_id: uuid.UUID) -> None:
    await _flag(conn, case_id, uuid.uuid4())
    row = (
        await conn.execute(
            sa.text("SELECT status, resolved_by, reason, evidence, created_at FROM flags")
        )
    ).one()
    assert (row.status, row.resolved_by, row.reason, row.evidence) == ("open", None, None, None)
    assert row.created_at is not None


async def test_severity_uses_the_contracts_values(
    conn: AsyncConnection, case_id: uuid.UUID
) -> None:
    for good in ("error", "warning", "info"):
        await _flag(conn, case_id, uuid.uuid4(), severity=good)
    await expect_db_error(
        conn, INSERT, c=case_id, t="field", e=uuid.uuid4(), code="X", s="critical"
    )


async def test_status_is_open_resolved_or_overridden(
    conn: AsyncConnection, case_id: uuid.UUID
) -> None:
    await _flag(conn, case_id, uuid.uuid4())
    for good in ("resolved", "overridden", "open"):
        await conn.execute(sa.text("UPDATE flags SET status = :s"), {"s": good})
    await expect_db_error(conn, "UPDATE flags SET status = 'pending'")


async def test_one_flag_per_entity_and_code(conn: AsyncConnection, case_id: uuid.UUID) -> None:
    entity = uuid.uuid4()
    await _flag(conn, case_id, entity, "DI-CHK-02")
    await _flag(conn, case_id, entity, "DI-CHK-01")  # another rule on the same field
    await _flag(conn, case_id, uuid.uuid4(), "DI-CHK-02")  # the same rule on another field
    await expect_db_error(conn, INSERT, c=case_id, t="field", e=entity, code="DI-CHK-02", s="info")


async def test_entity_type_and_id_are_free_form_so_later_features_can_use_them(
    conn: AsyncConnection, case_id: uuid.UUID
) -> None:
    # No foreign key and no CHECK on entity_type: components, calculations and so on come later.
    await _flag(conn, case_id, uuid.uuid4(), entity_type="income_component")


async def test_a_flag_needs_a_real_case_and_a_real_resolver(
    conn: AsyncConnection, case_id: uuid.UUID
) -> None:
    await expect_db_error(
        conn, INSERT, c=uuid.uuid4(), t="field", e=uuid.uuid4(), code="X", s="info"
    )
    await _flag(conn, case_id, uuid.uuid4())
    await expect_db_error(conn, "UPDATE flags SET resolved_by = :u", u=uuid.uuid4())


async def test_resolving_records_who_and_why(
    conn: AsyncConnection, case_id: uuid.UUID, user_id: uuid.UUID
) -> None:
    await _flag(conn, case_id, uuid.uuid4())
    await conn.execute(
        sa.text(
            "UPDATE flags SET status = 'overridden', resolved_by = :u, reason = 'checked the stub'"
        ),
        {"u": user_id},
    )
    row = (await conn.execute(sa.text("SELECT status, resolved_by, reason FROM flags"))).one()
    assert tuple(row) == ("overridden", user_id, "checked the stub")


async def test_evidence_holds_json(conn: AsyncConnection, case_id: uuid.UUID) -> None:
    await _flag(conn, case_id, uuid.uuid4())
    await conn.execute(
        sa.text("UPDATE flags SET evidence = CAST(:e AS jsonb)"),
        {"e": '{"page": 1, "line_ids": ["p1-L31"], "working": {"expected": "2033.61"}}'},
    )
    evidence = (await conn.execute(sa.text("SELECT evidence FROM flags"))).scalar_one()
    assert evidence["line_ids"] == ["p1-L31"] and evidence["working"]["expected"] == "2033.61"


async def test_deleting_a_case_removes_its_flags(conn: AsyncConnection, case_id: uuid.UUID) -> None:
    await _flag(conn, case_id, uuid.uuid4())
    await conn.execute(sa.text("DELETE FROM cases WHERE id = :c"), {"c": case_id})
    assert (await conn.execute(sa.text("SELECT count(*) FROM flags"))).scalar_one() == 0


async def test_fields_no_longer_carry_flags(conn: AsyncConnection) -> None:
    # fields.flags was dropped by 0002; flags live in their own table.
    rows = await conn.execute(
        sa.text(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_schema = 'public' AND table_name = 'fields'"
        )
    )
    assert "flags" not in {r[0] for r in rows}

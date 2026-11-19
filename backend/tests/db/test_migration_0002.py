"""0002 carries existing rows across, can be undone, and refuses to lose information.

These tests build a database at revision 0001 (the schema that is already on main), put realistic
rows in it with the OLD column names, then run the migration.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime
from typing import Any

import pytest
import sqlalchemy as sa
from alembic import command
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from tests.db.conftest import alembic_config

USER = uuid.UUID("11111111-1111-4111-8111-111111111111")
UW_FIRST = uuid.UUID("aaaaaaaa-0000-4000-8000-000000000001")
UW_SECOND = uuid.UUID("aaaaaaaa-0000-4000-8000-000000000002")
LM_ONLY = uuid.UUID("bbbbbbbb-0000-4000-8000-000000000001")
DOCUMENT = uuid.UUID("dddddddd-0000-4000-8000-000000000001")
PAGE = uuid.UUID("eeeeeeee-0000-4000-8000-000000000001")
RUN = uuid.UUID("ffffffff-0000-4000-8000-000000000001")
GONE_USER = uuid.UUID("22222222-2222-4222-8222-222222222222")  # an actor with no users row


def _at(day: int) -> datetime:
    return datetime(2026, 11, day, 9, 0, tzinfo=UTC)


async def _run(url: str, statements: list[tuple[str, dict[str, Any]]]) -> list[list[Any]]:
    engine = create_async_engine(url, poolclass=NullPool)
    try:
        async with engine.begin() as connection:
            last: list[list[Any]] = []
            for sql, params in statements:
                result = await connection.execute(sa.text(sql), params)
                last = [list(row) for row in result] if result.returns_rows else []
            return last
    finally:
        await engine.dispose()


def execute(url: str, sql: str, **params: Any) -> list[list[Any]]:
    return asyncio.run(_run(url, [(sql, params)]))


def seed_old_schema(url: str) -> None:
    """Rows as the schema on main (revision 0001) stores them."""
    statements: list[tuple[str, dict[str, Any]]] = [
        (
            "INSERT INTO users (id, username, name, role, password_hash) "
            "VALUES (:u, 'underwriter', 'Demo Underwriter', 'underwriter', 'h')",
            {"u": USER},
        ),
        # Created out of order on purpose: refs follow created_at, not insertion order.
        (
            "INSERT INTO cases (id, pillar, title, created_by, created_at, borrower_names) "
            "VALUES (:c, 'underwriting', 'Second', :u, :t, NULL)",
            {"c": UW_SECOND, "u": USER, "t": _at(12)},
        ),
        (
            "INSERT INTO cases (id, pillar, title, created_by, created_at, borrower_names) "
            "VALUES (:c, 'underwriting', 'First', :u, :t, ARRAY['Daniel Reyes', 'Maria Reyes'])",
            {"c": UW_FIRST, "u": USER, "t": _at(10)},
        ),
        (
            "INSERT INTO cases (id, pillar, title, created_by, created_at) "
            "VALUES (:c, 'loss_mitigation', 'Angela', :u, :t)",
            {"c": LM_ONLY, "u": USER, "t": _at(11)},
        ),
        (
            "INSERT INTO documents (id, case_id, file_name, file_key, sha256, mime, owner) "
            "VALUES (:d, :c, 'stub.pdf', 'k/stub.pdf', :h, 'application/pdf', 'Daniel Reyes')",
            {"d": DOCUMENT, "c": UW_FIRST, "h": "a" * 64},
        ),
        (
            "INSERT INTO pages (id, document_id, number, image_key, width, height) "
            "VALUES (:p, :d, 1, 'k/p1.png', 1000, 1400)",
            {"p": PAGE, "d": DOCUMENT},
        ),
        (
            "INSERT INTO lines (id, document_id, page_id, text, bbox) "
            "VALUES ('p1-L31', :d, :p, 'Net pay 2,033.61', '{}')",
            {"d": DOCUMENT, "p": PAGE},
        ),
        (
            "INSERT INTO extraction_runs (id, document_id, doc_type, active) "
            "VALUES (:r, :d, 'pay_stub', true)",
            {"r": RUN, "d": DOCUMENT},
        ),
        (
            "INSERT INTO fields (document_id, run_id, name, value, original_value, certainty, "
            "line_ids) VALUES (:d, :r, 'net_pay', '2033.61', '2033.61', 'high', "
            "ARRAY['p1-L31'])",
            {"d": DOCUMENT, "r": RUN},
        ),
        (
            "INSERT INTO jobs (kind, case_id) VALUES ('document_processing', :c)",
            {"c": UW_FIRST},
        ),
        # Old audit rows: a user id, plain 'system' and 'worker', and an actor with no users row.
        (
            "INSERT INTO audit_events (actor, case_id, action, entity) "
            "VALUES (:a, :c, 'case.created', :e)",
            {"a": str(USER), "c": UW_FIRST, "e": f"case:{UW_FIRST}"},
        ),
        (
            "INSERT INTO audit_events (actor, action, entity) "
            "VALUES ('system', 'case.deleted', 'case')",
            {},
        ),
        (
            "INSERT INTO audit_events (actor, case_id, action, entity) "
            "VALUES ('worker', :c, 'job.finished', :e)",
            {"c": LM_ONLY, "e": f"case:{LM_ONLY}"},
        ),
        (
            "INSERT INTO audit_events (actor, case_id, action, entity) "
            "VALUES (:a, :c, 'case.created', :e)",
            {"a": str(GONE_USER), "c": UW_SECOND, "e": f"case:{UW_SECOND}"},
        ),
    ]
    asyncio.run(_run(url, statements))


def test_existing_rows_survive_the_upgrade_and_the_downgrade(fresh_db_url: str) -> None:
    config = alembic_config(fresh_db_url)
    command.upgrade(config, "0001")
    seed_old_schema(fresh_db_url)

    command.upgrade(config, "0002")

    # cases: refs follow created_at within each pillar; borrower_names is now a jsonb array
    refs = execute(fresh_db_url, "SELECT title, case_ref, borrower_names FROM cases")
    assert {r[0]: (r[1], r[2]) for r in refs} == {
        "First": ("LP-0001", ["Daniel Reyes", "Maria Reyes"]),
        "Second": ("LP-0002", None),
        "Angela": ("LM-0001", None),
    }
    # ... and new cases continue after them
    assert execute(fresh_db_url, "SELECT nextval('case_ref_lp_seq')")[0][0] == 3
    assert execute(fresh_db_url, "SELECT nextval('case_ref_lm_seq')")[0][0] == 2

    doc = execute(
        fresh_db_url,
        "SELECT s3_key, borrower, size_bytes, doc_type_source, sha256 FROM documents",
    )[0]
    assert doc == ["k/stub.pdf", "Daniel Reyes", 0, None, "a" * 64]
    page = execute(fresh_db_url, "SELECT page_no, image_s3_key, created_at FROM pages")[0]
    assert page[:2] == [1, "k/p1.png"] and page[2] is not None
    line = execute(fresh_db_url, "SELECT id, line_ref, document_id, text FROM lines")[0]
    assert isinstance(line[0], uuid.UUID)
    assert line[1:] == ["p1-L31", DOCUMENT, "Net pay 2,033.61"]
    field = execute(fresh_db_url, "SELECT line_refs, normalized_value, created_at FROM fields")[0]
    assert field[0] == ["p1-L31"] and field[1] is None and field[2] is not None
    job = execute(fresh_db_url, "SELECT document_id, attempts FROM jobs")[0]
    assert job == [None, 0]

    audit = execute(
        fresh_db_url,
        "SELECT actor_id, role, entity_type, entity_id, action FROM audit_events ORDER BY id",
    )
    assert audit == [
        [USER, "underwriter", "case", UW_FIRST, "case.created"],
        [None, "system", "case", None, "case.deleted"],
        [None, "worker", "case", LM_ONLY, "job.finished"],
        [GONE_USER, "unknown", "case", UW_SECOND, "case.created"],  # no users row: role unknown
    ]
    # The append-only trigger was only off for the conversion.
    with pytest.raises(DBAPIError, match="append-only"):
        execute(fresh_db_url, "UPDATE audit_events SET reason = 'rewritten'")

    command.downgrade(config, "0001")

    cases = execute(fresh_db_url, "SELECT title, borrower_names FROM cases")
    assert {r[0]: r[1] for r in cases} == {
        "First": ["Daniel Reyes", "Maria Reyes"],
        "Second": None,
        "Angela": None,
    }
    assert execute(fresh_db_url, "SELECT file_key, owner FROM documents")[0] == [
        "k/stub.pdf",
        "Daniel Reyes",
    ]
    assert execute(fresh_db_url, "SELECT number, image_key FROM pages")[0] == [1, "k/p1.png"]
    assert execute(fresh_db_url, "SELECT id, document_id FROM lines")[0] == ["p1-L31", DOCUMENT]
    assert execute(fresh_db_url, "SELECT line_ids, flags FROM fields")[0] == [["p1-L31"], []]
    assert execute(fresh_db_url, "SELECT actor, entity FROM audit_events ORDER BY id") == [
        [str(USER), f"case:{UW_FIRST}"],
        ["system", "case"],
        ["worker", f"case:{LM_ONLY}"],
        [str(GONE_USER), f"case:{UW_SECOND}"],
    ]
    with pytest.raises(DBAPIError, match="append-only"):
        execute(fresh_db_url, "DELETE FROM audit_events")
    leftovers = execute(fresh_db_url, "SELECT sequencename FROM pg_sequences")
    assert not {"case_ref_lp_seq", "case_ref_lm_seq"} & {r[0] for r in leftovers}

    # and it can go forward again from the downgraded data
    command.upgrade(config, "head")
    assert {r[0] for r in execute(fresh_db_url, "SELECT case_ref FROM cases")} == {
        "LP-0001",
        "LP-0002",
        "LM-0001",
    }


def test_an_empty_database_upgrades_and_downgrades_one_step(fresh_db_url: str) -> None:
    config = alembic_config(fresh_db_url)
    command.upgrade(config, "0002")
    command.downgrade(config, "0001")
    version = execute(fresh_db_url, "SELECT version_num FROM alembic_version")
    assert version == [["0001"]]


def test_upgrade_refuses_to_drop_flags_that_hold_something(fresh_db_url: str) -> None:
    config = alembic_config(fresh_db_url)
    command.upgrade(config, "0001")
    seed_old_schema(fresh_db_url)
    execute(
        fresh_db_url,
        "UPDATE fields SET flags = CAST(:f AS jsonb)",
        f='[{"code": "DI-CHK-03", "severity": "warning", "message": "m"}]',
    )

    with pytest.raises(DBAPIError, match=r"fields\.flags is not empty"):
        command.upgrade(config, "0002")

    # Nothing was half-applied: still revision 0001 with the old columns.
    assert execute(fresh_db_url, "SELECT version_num FROM alembic_version") == [["0001"]]
    assert execute(fresh_db_url, "SELECT flags FROM fields")[0][0][0]["code"] == "DI-CHK-03"


def test_upgrade_refuses_an_audit_entity_it_cannot_split(fresh_db_url: str) -> None:
    config = alembic_config(fresh_db_url)
    command.upgrade(config, "0001")
    execute(
        fresh_db_url,
        "INSERT INTO audit_events (actor, action, entity) "
        "VALUES ('system', 'field.corrected', 'field:net_pay')",
    )

    with pytest.raises(DBAPIError, match=r"audit_events\.entity"):
        command.upgrade(config, "0002")

    assert execute(fresh_db_url, "SELECT version_num FROM alembic_version") == [["0001"]]
    assert execute(fresh_db_url, "SELECT entity FROM audit_events") == [["field:net_pay"]]

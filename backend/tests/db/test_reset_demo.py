"""``python -m app.db.reset_demo``: one command back to a clean demo state.

It empties the database by undoing and redoing the migrations (the audit table refuses DELETE and
TRUNCATE on purpose), removes the stored files, seeds the users and the two cases with their
profiles and Angela's hardship profile, and optionally uploads each borrower's documents and reads
them in-process (no Redis or worker). These tests run it against throwaway databases and moto S3.
"""

from __future__ import annotations

import asyncio
from datetime import date
from decimal import Decimal
from typing import Any

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from app.db import reset_demo as reset
from app.db.seed import case_id
from app.services.ingestion_config import get_ingestion_config
from app.storage import Storage
from tests.conftest import Rendered
from tests.db.conftest import S3_PREFIX, s3_keys

DANIEL = case_id("Daniel Reyes — purchase")
ANGELA = case_id("Angela Whitfield — hardship")
FAST = get_ingestion_config().model_copy(update={"render_dpi": 50})


def query(url: str, sql: str, **params: Any) -> list[Any]:
    async def run() -> list[Any]:
        engine = create_async_engine(url, poolclass=NullPool)
        try:
            async with engine.connect() as connection:
                return list((await connection.execute(sa.text(sql), params)).all())
        finally:
            await engine.dispose()

    return asyncio.run(run())


def state(url: str) -> dict[str, Any]:
    """What a demo looks like, without anything that changes from run to run."""
    return {
        "users": query(url, "SELECT username, role FROM users ORDER BY username"),
        "cases": query(
            url,
            "SELECT case_ref, pillar, borrower_names, employment_type, reference_date FROM cases "
            "ORDER BY case_ref",
        ),
        "documents": query(url, "SELECT count(*) FROM documents"),
        "profiles": query(url, "SELECT case_id, source FROM hardship_profiles"),
        "loan_records": query(
            url,
            "SELECT case_id, source, months_delinquent, unpaid_balance, arrears_amount "
            "FROM loan_records",
        ),
        "reports": query(
            url, "SELECT case_id, kind, source, status FROM reports ORDER BY kind, case_id"
        ),
        "report_parts": query(
            url,
            "SELECT (SELECT count(*) FROM findings), (SELECT count(*) FROM conditions), "
            "(SELECT count(*) FROM waterfall_results), (SELECT count(*) FROM lender_views), "
            "(SELECT count(*) FROM agent_runs), (SELECT count(*) FROM budget_lines)",
        ),
        "audit": query(url, "SELECT action, count(*) FROM audit_events GROUP BY 1 ORDER BY 1"),
        "revision": query(url, "SELECT version_num FROM alembic_version"),
    }


# --- the guards -----------------------------------------------------------------------------


def test_it_will_not_run_without_confirmation(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as stopped:
        reset.main([])

    assert stopped.value.code != 0
    assert "--yes" in capsys.readouterr().err


@pytest.mark.parametrize(
    "url",
    [
        "postgresql+asyncpg://copilot:secret@db.prod.example.com:5432/copilot",
        "postgresql+asyncpg://copilot:secret@10.1.2.3/copilot",
    ],
)
def test_it_refuses_a_database_that_is_not_local(url: str) -> None:
    with pytest.raises(reset.UnsafeTargetError) as refused:
        reset.check_target(url)

    assert "secret" not in str(refused.value)  # the password is never echoed


@pytest.mark.parametrize(
    "url",
    [
        "postgresql+asyncpg://copilot:copilot@localhost:5432/copilot",
        "postgresql+asyncpg://copilot:copilot@127.0.0.1:5432/copilot",
        "postgresql+asyncpg://copilot:copilot@postgres:5432/copilot",  # the compose network
    ],
)
def test_a_local_or_compose_database_is_allowed(url: str) -> None:
    reset.check_target(url)


# --- the state it leaves --------------------------------------------------------------------


def test_a_reset_leaves_users_cases_profiles_and_angelas_hardship_profile(
    fresh_db_url: str, s3_storage: Storage
) -> None:
    summary = reset.reset_demo(fresh_db_url, s3_storage, fake_reader=True)

    after = state(fresh_db_url)
    assert [(u.username, u.role) for u in after["users"]] == [
        ("admin", "admin"),
        ("lm_specialist", "lm_specialist"),
        ("underwriter", "underwriter"),
    ]
    angela, daniel = after["cases"]
    assert tuple(angela) == (
        "LM-0001",
        "loss_mitigation",
        ["Angela Whitfield"],
        "wage_earner",
        date(2026, 10, 16),
    )
    assert tuple(daniel) == (
        "LP-0001",
        "underwriting",
        ["Daniel Reyes"],
        "wage_earner",
        date(2026, 10, 12),
    )
    assert after["documents"][0][0] == 0  # nothing is uploaded unless asked
    # Angela's simulated servicing record: the rules read months delinquent from it.
    assert [tuple(r) for r in after["loan_records"]] == [
        (ANGELA, "synthetic", 3, Decimal("212400.00"), Decimal("5160.00"))
    ]
    assert [(p.case_id, p.source) for p in after["profiles"]] == [(ANGELA, "seeded_sample")]
    # The sample reports to review: Daniel's draft underwriting report and Angela's recommendation.
    assert sorted((r.case_id, r.kind, r.source, r.status) for r in after["reports"]) == sorted(
        [
            (DANIEL, "underwriting", "seeded_sample", "draft"),
            (ANGELA, "lm_recommendation", "seeded_sample", "draft"),
        ]
    )
    # findings, conditions, options, lender views, agent runs, budget lines (Angela's, five)
    assert tuple(after["report_parts"][0]) == (8, 6, 6, 1, 6, 5)
    assert after["revision"][0][0] == "0009"  # at the newest migration
    assert (summary.users, summary.cases, summary.documents) == (3, 2, 0)
    assert summary.hardship_profile_seeded
    assert summary.reports_seeded == 2 and summary.budget_computed


def test_a_second_reset_gives_the_same_state(fresh_db_url: str, s3_storage: Storage) -> None:
    reset.reset_demo(fresh_db_url, s3_storage, fake_reader=True)
    first = state(fresh_db_url)

    reset.reset_demo(fresh_db_url, s3_storage, fake_reader=True)

    assert state(fresh_db_url) == first  # history is cleared too, so the audit trail is the same


def test_a_reset_clears_what_was_there_before(fresh_db_url: str, s3_storage: Storage) -> None:
    reset.reset_demo(fresh_db_url, s3_storage, fake_reader=True)
    asyncio.run(_add_stray_case(fresh_db_url))  # a case somebody made while trying things out
    assert len(state(fresh_db_url)["cases"]) == 3

    reset.reset_demo(fresh_db_url, s3_storage, fake_reader=True)

    assert [c.case_ref for c in state(fresh_db_url)["cases"]] == ["LM-0001", "LP-0001"]


async def _add_stray_case(url: str) -> None:
    engine = create_async_engine(url, poolclass=NullPool)
    try:
        async with engine.begin() as connection:
            await connection.execute(
                sa.text(
                    "INSERT INTO cases (case_ref, pillar, title, created_by) "
                    "SELECT 'LP-0099', 'underwriting', 'Stray', id FROM users LIMIT 1"
                )
            )
    finally:
        await engine.dispose()


# --- uploading the documents ----------------------------------------------------------------


def test_with_upload_every_clean_document_is_read_and_angelas_profile_names_her_letter(
    fresh_db_url: str, s3_storage: Storage, rendered: Rendered
) -> None:
    summary = reset.reset_demo(
        fresh_db_url,
        s3_storage,
        upload=True,
        fake_reader=True,
        rendered_dir=rendered.out,
        ingestion_config=FAST,
    )

    counts = query(
        fresh_db_url,
        "SELECT c.case_ref, count(*) AS n FROM documents d JOIN cases c ON c.id = d.case_id "
        "GROUP BY 1 ORDER BY 1",
    )
    # Daniel's seven and Angela's eight; the withheld tax years and the broken set stay out.
    assert [(r.case_ref, r.n) for r in counts] == [("LM-0001", 8), ("LP-0001", 7)]
    assert summary.documents == 15
    stuck = query(
        fresh_db_url,
        "SELECT file_name, status FROM documents "
        "WHERE status IN ('uploaded', 'processing', 'failed')",
    )
    assert stuck == []  # all of them went through the whole pipeline
    types = query(
        fresh_db_url,
        "SELECT doc_type FROM documents WHERE case_id = :c ORDER BY doc_type",
        c=ANGELA,
    )
    assert "hardship_letter" in [t.doc_type for t in types]

    [profile] = query(
        fresh_db_url,
        "SELECT p.source, d.file_name, d.doc_type FROM hardship_profiles p "
        "JOIN documents d ON d.id = p.document_id",
    )
    assert (profile.source, profile.doc_type) == ("seeded_sample", "hardship_letter")
    assert not any("broken" in key or "withheld" in key for key in s3_keys())


def test_a_reset_removes_the_files_of_an_earlier_demo(
    fresh_db_url: str, s3_storage: Storage, rendered: Rendered
) -> None:
    reset.reset_demo(
        fresh_db_url,
        s3_storage,
        upload=True,
        fake_reader=True,
        rendered_dir=rendered.out,
        ingestion_config=FAST,
    )
    assert s3_keys()  # originals and page images

    summary = reset.reset_demo(fresh_db_url, s3_storage, fake_reader=True)

    assert s3_keys() == []
    assert summary.files_deleted > 0


def test_uploading_needs_storage_to_be_set_up(fresh_db_url: str, rendered: Rendered) -> None:
    with pytest.raises(reset.ResetError, match="S3_BUCKET"):
        reset.reset_demo(
            fresh_db_url,
            Storage(_settings(bucket="")),
            upload=True,
            fake_reader=True,
            rendered_dir=rendered.out,
        )


def test_a_missing_rendered_folder_says_how_to_make_it(
    fresh_db_url: str, s3_storage: Storage, tmp_path: Any
) -> None:
    with pytest.raises(reset.ResetError, match="make data"):
        reset.reset_demo(
            fresh_db_url,
            s3_storage,
            upload=True,
            fake_reader=True,
            rendered_dir=tmp_path / "nothing-here",
        )


def _settings(bucket: str) -> Any:
    from app.settings import Settings

    return Settings(_env_file=None, s3_bucket=bucket, s3_prefix=S3_PREFIX)

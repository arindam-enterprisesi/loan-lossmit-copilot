"""Database test setup: a throwaway Postgres database built by the real migration.

``TEST_DATABASE_URL`` points at a Postgres server where the user may create
databases (default: the docker compose one, ``docker compose up -d postgres``).
Each test session creates ``copilot_test_<hex>``, runs ``alembic upgrade head``
into it and drops it afterwards. Every test runs inside a transaction that is
rolled back. If Postgres is unreachable the tests skip locally, but fail when
``CI`` is set so a missing service can never pass silently.
"""

from __future__ import annotations

import asyncio
import os
import uuid
from collections.abc import AsyncIterator, Callable, Iterator
from pathlib import Path

import httpx
import pytest
import pytest_asyncio
import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from app.db.enums import Role
from app.db.models import User
from app.db.session import get_session
from app.main import app

BACKEND_DIR = Path(__file__).resolve().parents[2]
ADMIN_URL = os.environ.get(
    "TEST_DATABASE_URL", "postgresql+asyncpg://copilot:copilot@localhost:5432/copilot"
)


async def _admin(sql: str) -> None:
    engine = create_async_engine(ADMIN_URL, isolation_level="AUTOCOMMIT", poolclass=NullPool)
    try:
        async with engine.connect() as connection:
            await connection.execute(sa.text(sql))
    finally:
        await engine.dispose()


def _url_for(database: str) -> str:
    return make_url(ADMIN_URL).set(database=database).render_as_string(hide_password=False)


def alembic_config(url: str) -> Config:
    config = Config(str(BACKEND_DIR / "alembic.ini"))
    config.set_main_option("script_location", (BACKEND_DIR / "app/db/migrations").as_posix())
    config.set_main_option("sqlalchemy.url", url)
    config.attributes["configure_logger"] = False  # keep pytest's logging intact
    return config


def _require_postgres() -> None:
    try:
        asyncio.run(_admin("SELECT 1"))
    except Exception as exc:
        message = (
            f"Postgres not reachable at TEST_DATABASE_URL ({type(exc).__name__}); "
            "run `docker compose up -d postgres`"
        )
        if os.environ.get("CI"):
            pytest.fail(message)
        pytest.skip(message)


@pytest.fixture(scope="session")
def database_factory() -> Iterator[Callable[[], str]]:
    """Create empty throwaway databases and drop them all at the end of the session."""
    _require_postgres()
    created: list[str] = []

    def create() -> str:
        name = f"copilot_test_{uuid.uuid4().hex[:12]}"
        asyncio.run(_admin(f'CREATE DATABASE "{name}"'))
        created.append(name)
        return _url_for(name)

    yield create
    for name in created:
        asyncio.run(_admin(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))


@pytest.fixture(scope="session")
def migrated_db_url(database_factory: Callable[[], str]) -> str:
    """A database with the real migration applied. Shared, so tests must roll back."""
    url = database_factory()
    command.upgrade(alembic_config(url), "head")
    return url


@pytest.fixture
def fresh_db_url(database_factory: Callable[[], str]) -> str:
    """An empty database, for tests that run the migration themselves."""
    return database_factory()


@pytest_asyncio.fixture
async def conn(migrated_db_url: str) -> AsyncIterator[AsyncConnection]:
    engine = create_async_engine(migrated_db_url, poolclass=NullPool)
    try:
        async with engine.connect() as connection:
            transaction = await connection.begin()
            try:
                yield connection
            finally:
                await transaction.rollback()
    finally:
        await engine.dispose()


@pytest_asyncio.fixture
async def session(conn: AsyncConnection) -> AsyncIterator[AsyncSession]:
    # expire_on_commit=False matches app.db.session.get_sessionmaker.
    async with AsyncSession(
        bind=conn, join_transaction_mode="create_savepoint", expire_on_commit=False
    ) as s:
        yield s


@pytest_asyncio.fixture
async def client(session: AsyncSession) -> AsyncIterator[httpx.AsyncClient]:
    """The real app, talking to the test transaction (nothing is committed)."""

    async def use_test_session() -> AsyncIterator[AsyncSession]:
        yield session

    app.dependency_overrides[get_session] = use_test_session
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as c:
            yield c
    finally:
        app.dependency_overrides.clear()


async def expect_db_error(conn: AsyncConnection, sql: str, **params: object) -> sa.exc.DBAPIError:
    """Run a statement that must fail, inside a savepoint so the test transaction survives."""
    with pytest.raises(sa.exc.DBAPIError) as info:
        async with conn.begin_nested():
            await conn.execute(sa.text(sql), params)
    return info.value


@pytest_asyncio.fixture
async def user_id(conn: AsyncConnection) -> uuid.UUID:
    result = await conn.execute(
        sa.insert(User)
        .values(
            username=f"user-{uuid.uuid4().hex[:8]}",
            name="Test User",
            role=Role.UNDERWRITER,
            password_hash="not-a-real-hash",
        )
        .returning(User.id)
    )
    return result.scalar_one()


@pytest_asyncio.fixture
async def case_id(conn: AsyncConnection, user_id: uuid.UUID) -> uuid.UUID:
    return await insert_case(conn, user_id)


async def insert_case(
    conn: AsyncConnection,
    user_id: uuid.UUID,
    *,
    pillar: str = "underwriting",
    case_ref: str | None = None,
) -> uuid.UUID:
    """A case with a unique ref (taken from the pillar's sequence unless one is given)."""
    prefix, sequence = (
        ("LP", "case_ref_lp_seq")
        if pillar == "underwriting"
        else (
            "LM",
            "case_ref_lm_seq",
        )
    )
    if case_ref is None:
        number = (await conn.execute(sa.text(f"SELECT nextval('{sequence}')"))).scalar_one()
        case_ref = f"{prefix}-{number:04d}"
    result = await conn.execute(
        sa.text(
            "INSERT INTO cases (case_ref, pillar, title, created_by) "
            "VALUES (:r, :p, 'Test case', :u) RETURNING id"
        ),
        {"r": case_ref, "p": pillar, "u": user_id},
    )
    return result.scalar_one()


async def insert_document(
    conn: AsyncConnection, case_id: uuid.UUID, sha256: str | None = None
) -> uuid.UUID:
    result = await conn.execute(
        sa.text(
            "INSERT INTO documents (case_id, file_name, s3_key, sha256, mime, size_bytes) "
            "VALUES (:c, 'a.pdf', :k, :h, 'application/pdf', 1024) RETURNING id"
        ),
        {"c": case_id, "k": f"k/{uuid.uuid4().hex}.pdf", "h": sha256 or uuid.uuid4().hex * 2},
    )
    return result.scalar_one()


@pytest_asyncio.fixture
async def document_id(conn: AsyncConnection, case_id: uuid.UUID) -> uuid.UUID:
    return await insert_document(conn, case_id)

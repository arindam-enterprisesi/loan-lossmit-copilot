"""Reset the demo to a clean state with one command (``make reset-demo``).

    uv run python -m app.db.reset_demo --yes --upload [--fake-reader]

It empties the database, removes the files stored in S3, and rebuilds the demo: the three users, the
two cases with their profiles (Daniel Reyes, Pillar 1, and Angela Whitfield, Pillar 2), Angela's
simulated loan record and hardship profile, plus the sample reports to review (Daniel's draft
underwriting report with its six suggested conditions, Angela's waterfall, lender view and draft
report: all labelled ``seeded_sample``). With ``--upload`` it also uploads each borrower's
generated documents and reads them straight away, in this process, with no Redis and no worker
(``--fake-reader`` uses the rule-based reader, for when no model provider works). Run
``make data`` first to generate the documents.

The database is emptied by undoing and redoing the migrations: the audit table refuses DELETE and
TRUNCATE on purpose, so this is also the only way to clear its history. That makes this script
destructive, so it needs ``--yes`` and refuses any database that is not local.

Everything is synthetic. Nothing here calls a model unless ``--upload`` runs without
``--fake-reader`` and ``PIPELINE_LLM`` allows it.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
import time
import uuid
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.db.demo.hardship import seed_hardship_profile
from app.db.demo.loan_record import seed_loan_record
from app.db.demo.reports import seed_lm_recommendation, seed_underwriting_report
from app.db.enums import EmploymentType, Pillar
from app.db.seed import DEMO_CASES, DEMO_USERS, case_id, seed, user_id
from app.services import budget_runs, hardship_runs
from app.services import cases as case_service
from app.services import documents as document_service
from app.services.fake_reader import FakeClassifier, FakeExtractor
from app.services.ingestion_config import IngestionConfig, get_ingestion_config
from app.services.security import CurrentUser
from app.services.transaction_labels import FakeLabeller, TransactionLabeller, get_labeller
from app.settings import REPO_ROOT, get_settings
from app.storage import Storage, StorageError
from app.worker import process_documents

logger = logging.getLogger(__name__)

BACKEND_DIR = Path(__file__).resolve().parents[2]
SYNTHETIC_DIR = REPO_ROOT / "data" / "synthetic"
SCENARIOS_DIR = SYNTHETIC_DIR / "scenarios"
DEFAULT_RENDERED_DIR = SYNTHETIC_DIR / "rendered"
# Hosts that are this machine or the compose network. Anything else could be someone's real data.
LOCAL_HOSTS = frozenset({"localhost", "127.0.0.1", "::1", "postgres"})


class ResetError(Exception):
    """The reset cannot run as asked; the message says what to do."""


class UnsafeTargetError(ResetError):
    """The database is not local."""


@dataclass(frozen=True)
class ResetSummary:
    users: int
    cases: int
    documents: int
    files_deleted: int
    hardship_profile_seeded: bool
    seconds: float
    reports_seeded: int = 0
    budget_computed: bool = False


@dataclass(frozen=True)
class Scenario:
    """One demo borrower: the case they belong to and the folder of their generated documents."""

    folder: str  # also the scenario file's name, e.g. "daniel_reyes"
    title: str
    name: str
    pillar: Pillar
    reference_date: date

    @property
    def case_id(self) -> uuid.UUID:
        return case_id(self.title)


def check_target(database_url: str) -> None:
    """Refuse a database that is not on this machine. The password is never echoed."""
    host = make_url(database_url).host
    if host is not None and host not in LOCAL_HOSTS:
        raise UnsafeTargetError(
            f"refusing to reset a database on {host!r}: only a local database "
            f"({', '.join(sorted(LOCAL_HOSTS))}) may be emptied"
        )


def load_scenarios() -> list[Scenario]:
    """The two demo borrowers, from ``data/synthetic/scenarios``."""
    titles = {title for title, *_ in DEMO_CASES}
    found: list[Scenario] = []
    for path in sorted(SCENARIOS_DIR.glob("*.json")):
        borrower = json.loads(path.read_text(encoding="utf-8"))["borrower"]
        if borrower["case_title"] not in titles:
            raise ResetError(f"{path.name}: case {borrower['case_title']!r} is not a demo case")
        found.append(
            Scenario(
                folder=path.stem,
                title=borrower["case_title"],
                name=borrower["name"],
                pillar=Pillar(borrower["pillar"]),
                reference_date=date.fromisoformat(borrower["reference_date"]),
            )
        )
    return found


# --- 1. the files ---------------------------------------------------------------------------


async def _stored_keys(url: str) -> list[str]:
    """Every S3 key the database knows about (originals and page images); none if no tables yet."""
    engine = create_async_engine(url, poolclass=NullPool)
    try:
        async with engine.connect() as connection:
            tables = (
                await connection.execute(
                    sa.text(
                        "SELECT to_regclass('public.documents') IS NOT NULL "
                        "AND to_regclass('public.pages') IS NOT NULL"
                    )
                )
            ).scalar_one()
            if not tables:
                return []
            originals = await connection.execute(sa.text("SELECT s3_key FROM documents"))
            images = await connection.execute(sa.text("SELECT image_s3_key FROM pages"))
            return [row[0] for row in originals] + [row[0] for row in images]
    finally:
        await engine.dispose()


def _delete_stored_files(storage: Storage, keys: list[str]) -> int:
    """Remove the files; a failure is logged and counted, never a reason to stop the reset."""
    deleted = failed = 0
    for key in keys:
        try:
            storage.delete(key)
            deleted += 1
        except StorageError as exc:
            failed += 1
            logger.warning("could not remove a stored file: %s", exc)
    if failed:
        logger.warning("%d stored file(s) could not be removed", failed)
    return deleted


# --- 2. the schema --------------------------------------------------------------------------


def _alembic_config(url: str) -> Config:
    config = Config(str(BACKEND_DIR / "alembic.ini"))
    config.set_main_option(
        "script_location", (BACKEND_DIR / "app" / "db" / "migrations").as_posix()
    )
    config.set_main_option("sqlalchemy.url", url.replace("%", "%%"))
    config.attributes["configure_logger"] = False
    return config


def _recreate_schema(url: str) -> None:
    """Undo every migration, then apply them all. Alembic needs to run outside an event loop."""
    config = _alembic_config(url)
    command.downgrade(config, "base")
    command.upgrade(config, "head")


# --- 3. the demo data -----------------------------------------------------------------------


class _InlineQueue:
    """Remembers what an upload queued. The reset reads the documents itself, so nothing runs it."""

    async def enqueue(self, function: str, *args: Any, job_id: str) -> None:
        return None


def _user_for(title: str) -> CurrentUser:
    """The seeded user who owns a demo case, as a logged-in user."""
    username = next(creator for t, _, _, creator in DEMO_CASES if t == title)
    name, role = next((n, r) for u, n, r in DEMO_USERS if u == username)
    return CurrentUser(id=str(user_id(username)), name=name, role=role)


async def _set_profile(session: AsyncSession, scenario: Scenario) -> None:
    # Both demo borrowers are wage earners (pay stubs, W-2); the scenario files do not say so.
    view = await case_service.set_profile(
        session,
        _user_for(scenario.title),
        scenario.case_id,
        borrower_names=[scenario.name],
        employment_type=EmploymentType.WAGE_EARNER,
        reference_date=scenario.reference_date,
    )
    if view is None:
        raise ResetError(f"the demo case {scenario.title!r} was not created")


async def _upload_and_read(
    factory: async_sessionmaker[AsyncSession],
    storage: Storage,
    scenario: Scenario,
    rendered_dir: Path,
    config: IngestionConfig,
    *,
    fake_reader: bool,
) -> int:
    """Upload a borrower's clean documents (not ``withheld/`` or the broken set), then read them."""
    files = sorted((rendered_dir / scenario.folder).glob("*.pdf"))
    validated = [
        document_service.validate_file(f.name, f.read_bytes(), config.max_file_bytes) for f in files
    ]
    async with factory() as session:
        outcome = await document_service.upload_documents(
            session,
            storage,
            _InlineQueue(),
            _user_for(scenario.title),
            scenario.case_id,
            validated,
            None,
        )
    context: dict[str, Any] = {
        "storage": storage,
        "session_factory": factory,
        "ingestion_config": config,
    }
    if fake_reader:
        context |= {"classifier": FakeClassifier(), "extractor": FakeExtractor()}
    await process_documents(
        context, str(outcome.job.id), [str(view.document.id) for view in outcome.documents]
    )
    return len(outcome.documents)


async def _populate(
    url: str,
    storage: Storage,
    scenarios: list[Scenario],
    *,
    upload: bool,
    fake_reader: bool,
    rendered_dir: Path,
    config: IngestionConfig,
) -> tuple[int, int, int, bool, int, bool]:
    """Seed users, cases and profiles; optionally upload and read; seed the hardship profile."""
    engine = create_async_engine(url, poolclass=NullPool)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with factory() as session:
            seeded = await seed(session, get_settings().demo_password.get_secret_value())
            for scenario in scenarios:
                await _set_profile(session, scenario)
            await session.commit()
        documents = 0
        if upload:
            for scenario in scenarios:
                documents += await _upload_and_read(
                    factory, storage, scenario, rendered_dir, config, fake_reader=fake_reader
                )
        hardship_seeded = False
        budget_built = False
        reports = 0
        async with factory() as session:
            for scenario in scenarios:
                if scenario.pillar is Pillar.LOSS_MITIGATION:
                    record = json.loads(
                        (SCENARIOS_DIR / f"{scenario.folder}.json").read_text(encoding="utf-8")
                    )["loan_record"]
                    await seed_loan_record(session, scenario.case_id, record)
                    await seed_hardship_profile(session, scenario.case_id)
                    await seed_lm_recommendation(session, scenario.case_id)
                    hardship_seeded = True
                else:
                    await seed_underwriting_report(session, scenario.case_id)
                reports += 1
            await session.commit()  # the seeds are safe before anything that can fail
        async with factory() as session:
            for scenario in scenarios:
                if scenario.pillar is Pillar.LOSS_MITIGATION:
                    budget_built = await _build_budget(
                        session, scenario, upload=upload, fake_reader=fake_reader
                    )
            await session.commit()
        return (
            seeded.users_created,
            seeded.cases_created,
            documents,
            hardship_seeded,
            reports,
            budget_built,
        )
    finally:
        await engine.dispose()


async def _build_budget(
    session: AsyncSession, scenario: Scenario, *, upload: bool, fake_reader: bool
) -> bool:
    """Build the loss mitigation case's budget on its seeded profile from whatever was uploaded.

    The statements' lines are labelled by the model (or the keyword labeller with
    ``--fake-reader``). With no upload there are no documents, so the budget says what it cannot
    compute. A labelling failure must not stop the reset: the budget is then built from no labels
    and says so.
    """
    view = await hardship_runs.latest(session, scenario.case_id)
    if view is None:
        return False
    labeller: TransactionLabeller | None = None
    if upload:
        labeller = FakeLabeller() if fake_reader else get_labeller()
    try:
        await budget_runs.compute_for_run(session, view.run, labeller=labeller)
    except Exception as exc:
        logger.warning("budget not built with labels (%s); building it without", type(exc).__name__)
        await session.rollback()
        await budget_runs.compute_for_run(session, view.run)
    return True


# --- the whole reset ------------------------------------------------------------------------


def reset_demo(
    database_url: str,
    storage: Storage,
    *,
    upload: bool = False,
    fake_reader: bool = False,
    rendered_dir: Path | None = None,
    ingestion_config: IngestionConfig | None = None,
) -> ResetSummary:
    """Empty the database and the stored files, then rebuild the demo. See the module docstring."""
    started = time.monotonic()
    check_target(database_url)
    rendered = rendered_dir or DEFAULT_RENDERED_DIR
    config = ingestion_config or get_ingestion_config()
    scenarios = load_scenarios()

    # Check what the upload needs before anything is emptied.
    if upload:
        try:
            _ = storage.bucket  # raises when S3_BUCKET is not set
        except StorageError:
            raise ResetError(
                "uploading needs S3_BUCKET (and AWS access) to be set in .env"
            ) from None
        if not any(list((rendered / s.folder).glob("*.pdf")) for s in scenarios):
            raise ResetError(f"no generated documents in {rendered}; run `make data` first")

    keys = asyncio.run(_stored_keys(database_url))
    files_deleted = _delete_stored_files(storage, keys)
    _recreate_schema(database_url)
    users, cases, documents, hardship, reports, budget = asyncio.run(
        _populate(
            database_url,
            storage,
            scenarios,
            upload=upload,
            fake_reader=fake_reader,
            rendered_dir=rendered,
            config=config,
        )
    )
    return ResetSummary(
        users=users,
        cases=cases,
        documents=documents,
        files_deleted=files_deleted,
        hardship_profile_seeded=hardship,
        seconds=time.monotonic() - started,
        reports_seeded=reports,
        budget_computed=budget,
    )


# --- command line ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m app.db.reset_demo",
        description="Empty the demo database and stored files, then rebuild the demo.",
    )
    parser.add_argument("--yes", action="store_true", help="confirm that the database is emptied")
    parser.add_argument(
        "--upload", action="store_true", help="also upload and read each borrower's documents"
    )
    parser.add_argument(
        "--fake-reader",
        action="store_true",
        help="read documents with the rule-based reader instead of a model provider",
    )
    parser.add_argument(
        "--rendered-dir",
        type=Path,
        default=None,
        help=f"generated documents (default {DEFAULT_RENDERED_DIR})",
    )
    return parser


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not args.yes:
        parser.error("this empties the database and the stored files: pass --yes to confirm")
    settings = get_settings()
    print("Resetting the demo ...", flush=True)
    try:
        summary = reset_demo(
            settings.database_url,
            Storage(settings),
            upload=args.upload,
            fake_reader=args.fake_reader,
            rendered_dir=args.rendered_dir,
        )
    except ResetError as exc:
        print(f"Reset stopped: {exc}", file=sys.stderr)
        raise SystemExit(1) from None
    print(
        f"Done in {summary.seconds:.0f} s: {summary.users} users, {summary.cases} cases, "
        f"{summary.documents} documents uploaded, {summary.files_deleted} old file(s) removed, "
        f"hardship profile {'seeded' if summary.hardship_profile_seeded else 'not seeded'}, "
        f"{summary.reports_seeded} sample report(s) seeded."
    )


if __name__ == "__main__":
    main()

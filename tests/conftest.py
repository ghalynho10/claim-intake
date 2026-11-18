"""Shared fixtures. Tests run against a real PostgreSQL test database.

Needs TEST_DATABASE_URL (the claim_app role on a database whose name ends in
`_test`), MIGRATE_DATABASE_URL and ADMIN_DATABASE_URL, from the environment
only: tests never read `.env` (run `uv run --env-file .env pytest` to load it
into the environment yourself). The owner URL is pointed at the test database automatically. The
session bootstraps and migrates the test database once (creating it if missing).
"""

from collections.abc import Iterator
from pathlib import Path

import psycopg
import pytest
from fastapi.testclient import TestClient
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import Engine
from sqlalchemy.orm import Session

from claim_intake.api.app import create_app
from claim_intake.config import MigrateSettings, PostgresUrl, Settings
from claim_intake.db import migrate
from claim_intake.db.engine import make_engine
from claim_intake.db.urls import CHECKPOINT_SCHEMA, database_name, with_database

ROOT = Path(__file__).resolve().parent.parent
CHECKPOINT_TABLES = ("checkpoints", "checkpoint_blobs", "checkpoint_writes")


class _TestEnv(BaseSettings):
    model_config = SettingsConfigDict(env_file=None, extra="ignore")

    test_database_url: PostgresUrl | None = None
    migrate_database_url: PostgresUrl | None = None
    admin_database_url: PostgresUrl | None = None


@pytest.fixture(scope="session")
def migrate_settings() -> MigrateSettings:
    env = _TestEnv()
    missing = [
        name
        for name in ("test_database_url", "migrate_database_url", "admin_database_url")
        if getattr(env, name) is None
    ]
    if missing:
        pytest.fail(f"set {', '.join(n.upper() for n in missing)} (see .env.example)")
    assert env.test_database_url and env.migrate_database_url and env.admin_database_url

    test_db = database_name(env.test_database_url)
    if not test_db.endswith("_test"):
        pytest.fail("refusing to run: the TEST_DATABASE_URL database name must end in _test")

    return MigrateSettings(
        _env_file=None,
        database_url=env.test_database_url,
        migrate_database_url=with_database(env.migrate_database_url, test_db),
        admin_database_url=env.admin_database_url,
        log_level="WARNING",
    )


@pytest.fixture(scope="session")
def settings(migrate_settings: MigrateSettings) -> Iterator[Settings]:
    migrate.run(migrate_settings, pyproject=ROOT / "pyproject.toml")
    yield Settings(_env_file=None, database_url=migrate_settings.database_url, log_level="WARNING")
    # Checkpointer tests use uuid thread ids; clear their rows at the end.
    with psycopg.connect(migrate_settings.migrate_database_url, autocommit=True) as conn:
        tables = ", ".join(f"{CHECKPOINT_SCHEMA}.{t}" for t in CHECKPOINT_TABLES)
        conn.execute(f"TRUNCATE {tables}")


@pytest.fixture(scope="session")
def engine(settings: Settings) -> Iterator[Engine]:
    """Connects as claim_app, so tests exercise the real grants."""
    engine = make_engine(settings.database_url)
    yield engine
    engine.dispose()


@pytest.fixture
def db_session(engine: Engine) -> Iterator[Session]:
    """A session whose work is rolled back after the test (SAVEPOINT based)."""
    with engine.connect() as conn:
        outer = conn.begin()
        session = Session(bind=conn, join_transaction_mode="create_savepoint")
        try:
            yield session
        finally:
            session.close()
            outer.rollback()


@pytest.fixture
def client(settings: Settings) -> Iterator[TestClient]:
    with TestClient(create_app(settings)) as client:
        yield client

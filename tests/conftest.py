"""Shared fixtures. Tests run against a real PostgreSQL test database.

Needs TEST_DATABASE_URL (the claim_app role on a database whose name ends in
`_test`), MIGRATE_DATABASE_URL and ADMIN_DATABASE_URL, from the environment
only: tests never read `.env` (run `uv run --env-file .env pytest` to load it
into the environment yourself). The owner URL is pointed at the test database automatically. The
session bootstraps and migrates the test database once (creating it if missing).
"""

from collections.abc import Callable, Iterator, Sequence
from contextlib import AbstractContextManager, contextmanager
from dataclasses import dataclass
from pathlib import Path

import psycopg
import pytest
from fastapi.testclient import TestClient
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import Engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from claim_intake.api.app import create_app
from claim_intake.config import MigrateSettings, PostgresUrl, Settings
from claim_intake.db import migrate
from claim_intake.db.engine import make_engine
from claim_intake.db.models import Claim, Document, EvidenceUnit
from claim_intake.db.states import ClaimStatus, DocumentKind
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


@dataclass
class ClaimChain:
    claim: Claim
    document: Document
    units: list[EvidenceUnit]


ChainFactory = Callable[..., ClaimChain]
Violates = Callable[[str], AbstractContextManager[None]]


@pytest.fixture
def claim_chain(db_session: Session) -> ChainFactory:
    """Builds a claim, one document at the claim's version, and its ordered
    evidence units: the chain most data model tests stand on."""

    def make(
        unit_texts: Sequence[str] = ("Policy number: P-1", "Loss date: 2026-01-02"),
        claim: Claim | None = None,
        claim_version: int = 1,
    ) -> ClaimChain:
        if claim is None:
            claim = Claim(status=ClaimStatus.EXTRACTING)
            db_session.add(claim)
            db_session.flush()
        document = Document(
            claim_id=claim.id,
            claim_version=claim_version,
            kind=DocumentKind.EMAIL,
            text="\n".join(unit_texts),
        )
        db_session.add(document)
        db_session.flush()
        units = [
            EvidenceUnit(document_id=document.id, position=i, text=t)
            for i, t in enumerate(unit_texts)
        ]
        db_session.add_all(units)
        db_session.flush()
        return ClaimChain(claim, document, units)

    return make


@pytest.fixture
def violates(db_session: Session) -> Violates:
    """`with violates("uq_x"): ...` expects the block's flush or statement to
    fail on exactly that constraint, inside a savepoint so the test goes on."""

    @contextmanager
    def check(constraint: str) -> Iterator[None]:
        with pytest.raises(IntegrityError) as caught, db_session.begin_nested():
            yield
            db_session.flush()
        diag = getattr(caught.value.orig, "diag", None)
        assert diag is not None and diag.constraint_name == constraint

    return check


@pytest.fixture
def client(settings: Settings) -> Iterator[TestClient]:
    with TestClient(create_app(settings)) as client:
        yield client

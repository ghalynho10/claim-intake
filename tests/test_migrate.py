"""Bootstrap and migrate: schemas, roles, grants, checkpoint tables."""

from pathlib import Path

import psycopg
import pytest
from alembic import command
from alembic.config import Config
from psycopg import sql
from sqlalchemy import Engine, text
from sqlalchemy.exc import ProgrammingError
from sqlalchemy.orm import Session

from claim_intake.config import MigrateSettings
from claim_intake.db import migrate
from claim_intake.db.urls import database_name, username, with_database

PYPROJECT = Path(__file__).resolve().parent.parent / "pyproject.toml"

# Spec 0002, AC-1: the model tables, by schema.
EXPECTED_TABLES = {
    ("public", "claim"),
    ("public", "document"),
    ("public", "evidence_unit"),
}


def test_schemas_exist_and_belong_to_owner(
    engine: Engine, migrate_settings: MigrateSettings
) -> None:
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT nspname, pg_get_userbyid(nspowner) FROM pg_namespace "
                "WHERE nspname IN ('public', 'claims_system', 'langgraph')"
            )
        ).all()
    owners = dict(rows)
    assert set(owners) == {"public", "claims_system", "langgraph"}
    assert set(owners.values()) == {username(migrate_settings.migrate_database_url)}


def test_checkpoint_tables_live_in_langgraph_schema_only(engine: Engine) -> None:
    with engine.connect() as conn:
        found = (
            conn.execute(
                text(
                    "SELECT table_schema FROM information_schema.tables "
                    "WHERE table_name = 'checkpoints'"
                )
            )
            .scalars()
            .all()
        )
    assert found == ["langgraph"]


def test_alembic_version_table_in_public(engine: Engine) -> None:
    with engine.connect() as conn:
        assert (
            conn.execute(text("SELECT to_regclass('public.alembic_version')")).scalar() is not None
        )


def test_app_role_can_write_checkpoint_tables(db_session: Session) -> None:
    db_session.execute(text("INSERT INTO langgraph.checkpoint_migrations (v) VALUES (-1)"))
    assert (
        db_session.execute(
            text("SELECT count(*) FROM langgraph.checkpoint_migrations WHERE v = -1")
        ).scalar()
        == 1
    )


@pytest.mark.parametrize("schema", ["public", "claims_system", "langgraph"])
def test_app_role_cannot_create_tables(db_session: Session, schema: str) -> None:
    with pytest.raises(ProgrammingError, match="permission denied"):
        db_session.execute(text(f"CREATE TABLE {schema}.not_allowed (id int)"))


def test_mcp_role_exists_without_login(engine: Engine) -> None:
    with engine.connect() as conn:
        can_login = conn.execute(
            text("SELECT rolcanlogin FROM pg_roles WHERE rolname = 'claim_mcp'")
        ).scalar()
    assert can_login is False


def _alembic_config(owner_url: str) -> Config:
    config = Config(toml_file=PYPROJECT)
    config.set_main_option("script_location", str(PYPROJECT.parent / "migrations"))
    config.attributes["database_url"] = owner_url
    return config


def test_autogenerate_sees_no_drift(migrate_settings: MigrateSettings) -> None:
    """Models match the database, and Alembic leaves its own version table and
    the checkpointer's schema alone."""
    command.check(_alembic_config(migrate_settings.migrate_database_url))


def _model_tables(owner_url: str) -> set[tuple[str, str]]:
    with psycopg.connect(owner_url) as conn:
        rows = conn.execute(
            "SELECT table_schema, table_name FROM information_schema.tables "
            "WHERE table_schema IN ('public', 'claims_system') AND table_name <> 'alembic_version'"
        ).fetchall()
    return {(schema, name) for schema, name in rows}


def _schemas(owner_url: str) -> set[str]:
    with psycopg.connect(owner_url) as conn:
        rows = conn.execute(
            "SELECT nspname FROM pg_namespace "
            "WHERE nspname IN ('public', 'claims_system', 'langgraph')"
        ).fetchall()
    return {name for (name,) in rows}


def test_migration_round_trip_on_empty_database(migrate_settings: MigrateSettings) -> None:
    """AC-1: upgrade head on an empty database, downgrade to base (tables gone,
    schemas kept), upgrade head again. Runs on its own throwaway database so the
    shared test database is never emptied."""
    test_db = database_name(migrate_settings.database_url)
    roundtrip_db = test_db.removesuffix("_test") + "_roundtrip_test"
    settings = MigrateSettings(
        _env_file=None,
        database_url=with_database(migrate_settings.database_url, roundtrip_db),
        migrate_database_url=with_database(migrate_settings.migrate_database_url, roundtrip_db),
        admin_database_url=migrate_settings.admin_database_url,
        log_level="WARNING",
    )
    owner_url = settings.migrate_database_url
    drop = sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(sql.Identifier(roundtrip_db))

    with psycopg.connect(settings.admin_database_url, autocommit=True) as admin:
        admin.execute(drop)
    try:
        migrate.run(settings, pyproject=PYPROJECT)  # bootstrap creates the database
        assert _model_tables(owner_url) == EXPECTED_TABLES

        command.downgrade(_alembic_config(owner_url), "base")
        assert _model_tables(owner_url) == set()
        assert _schemas(owner_url) == {"public", "claims_system", "langgraph"}

        command.upgrade(_alembic_config(owner_url), "head")
        assert _model_tables(owner_url) == EXPECTED_TABLES
    finally:
        with psycopg.connect(settings.admin_database_url, autocommit=True) as admin:
            admin.execute(drop)


def test_migrate_is_idempotent(migrate_settings: MigrateSettings, engine: Engine) -> None:
    migrate.run(migrate_settings, pyproject=PYPROJECT)
    with engine.connect() as conn:
        assert conn.execute(text("SELECT 1")).scalar() == 1

"""Bootstrap and migrate: schemas, roles, grants, checkpoint tables."""

from pathlib import Path

import pytest
from sqlalchemy import Engine, text
from sqlalchemy.exc import ProgrammingError
from sqlalchemy.orm import Session

from claim_intake.config import MigrateSettings
from claim_intake.db import migrate
from claim_intake.db.urls import username

PYPROJECT = Path(__file__).resolve().parent.parent / "pyproject.toml"


def test_schemas_exist_and_belong_to_owner(engine: Engine, migrate_settings: MigrateSettings) -> None:
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
        found = conn.execute(
            text(
                "SELECT table_schema FROM information_schema.tables "
                "WHERE table_name = 'checkpoints'"
            )
        ).scalars().all()
    assert found == ["langgraph"]


def test_alembic_version_table_in_public(engine: Engine) -> None:
    with engine.connect() as conn:
        assert conn.execute(text("SELECT to_regclass('public.alembic_version')")).scalar() is not None


def test_app_role_can_write_checkpoint_tables(db_session: Session) -> None:
    db_session.execute(
        text(
            "INSERT INTO langgraph.checkpoint_migrations (v) VALUES (-1)"
        )
    )
    assert db_session.execute(
        text("SELECT count(*) FROM langgraph.checkpoint_migrations WHERE v = -1")
    ).scalar() == 1


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


def test_autogenerate_sees_no_drift(migrate_settings: MigrateSettings) -> None:
    """Models match the database, and Alembic leaves its own version table and
    the checkpointer's schema alone."""
    from alembic import command
    from alembic.config import Config

    config = Config(toml_file=PYPROJECT)
    config.set_main_option("script_location", str(PYPROJECT.parent / "migrations"))
    config.attributes["database_url"] = migrate_settings.migrate_database_url
    command.check(config)  # raises if autogenerate would emit operations


def test_migrate_is_idempotent(migrate_settings: MigrateSettings, engine: Engine) -> None:
    migrate.run(migrate_settings, pyproject=PYPROJECT)
    with engine.connect() as conn:
        assert conn.execute(text("SELECT 1")).scalar() == 1

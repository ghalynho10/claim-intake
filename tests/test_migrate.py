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
    ("public", "extracted_field"),
    ("public", "citation"),
    ("public", "claim_decision"),
    ("public", "decision_log"),
    ("claims_system", "claim_record"),
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


# Spec 0002, Constraint names: every unique, foreign key, CHECK and index name,
# by table, besides the primary keys (added below).
CONSTRAINT_NAMES = {
    "claim": {"ck_claim_status", "ck_claim_version_min"},
    "document": {
        "uq_document_claim_id",
        "fk_document_claim_id_claim",
        "ck_document_kind",
        "ck_document_claim_version_min",
    },
    "evidence_unit": {
        "uq_evidence_unit_document_id",
        "fk_evidence_unit_document_id_document",
        "ck_evidence_unit_position_min",
    },
    "extracted_field": {
        "uq_extracted_field_claim_id",
        "fk_extracted_field_claim_id_claim",
        "ck_extracted_field_evidence_status",
        "ck_extracted_field_value_origin",
        "ck_extracted_field_review_status",
        "ck_extracted_field_found_has_value",
    },
    "citation": {
        "fk_citation_field_id_extracted_field",
        "fk_citation_document_id_evidence_unit",
        "ck_citation_start_min",
        "ck_citation_range",
        "ix_citation_field_id",
        "ix_citation_document_id",
    },
    "claim_decision": {
        "uq_claim_decision_claim_id",
        "fk_claim_decision_claim_id_claim",
        "ck_claim_decision_outcome",
        "ck_claim_decision_write_status",
        "ck_claim_decision_claim_version_min",
        "ck_claim_decision_payload_object",
        "ck_claim_decision_reviewer_name_set",
        "ck_claim_decision_outcome_fields",
    },
    "decision_log": {
        "fk_decision_log_claim_id_claim",
        "fk_decision_log_decision_id_claim_decision",
        "ck_decision_log_action",
        "ck_decision_log_claim_version_min",
        "ck_decision_log_reviewer_name_set",
        "ck_decision_log_action_fields",
        "ix_decision_log_claim_id",
        "ix_decision_log_decision_id",
    },
    "claim_record": {
        "uq_claim_record_idempotency_key",
        "uq_claim_record_claim_id",
        "ck_claim_record_claim_version_min",
        "ck_claim_record_payload_object",
    },
}

# Postgres 18 also lists each NOT NULL column in pg_constraint (contype 'n',
# named `<table>_<column>_not_null` by Postgres itself). They are column
# nullability, not named constraints of the model, so they are left out here;
# `alembic check` covers nullability.
_DB_NAMES = text(
    """
    SELECT c.relname, con.conname
    FROM pg_constraint con
    JOIN pg_class c ON c.oid = con.conrelid
    JOIN pg_namespace n ON n.oid = c.relnamespace
    WHERE n.nspname IN ('public', 'claims_system')
      AND c.relname <> 'alembic_version'
      AND con.contype <> 'n'
    UNION
    SELECT tablename, indexname
    FROM pg_indexes
    WHERE schemaname IN ('public', 'claims_system') AND tablename <> 'alembic_version'
    """
)


def test_constraint_names_match_the_spec(engine: Engine) -> None:
    """AC-1: the database holds exactly the spec's names, each within
    Postgres's 63 character limit (a longer name would be silently cut)."""
    expected = {
        (table, name)
        for table, names in CONSTRAINT_NAMES.items()
        for name in names | {f"pk_{table}"}
    }
    assert all(len(name) <= 63 for _, name in expected)
    assert {table for _, table in EXPECTED_TABLES} == set(CONSTRAINT_NAMES)

    with engine.connect() as conn:
        found = {(table, name) for table, name in conn.execute(_DB_NAMES).all()}

    assert found == expected
    assert all(len(name) <= 63 for _, name in found)


def test_citation_index_covers_document_and_start(engine: Engine) -> None:
    with engine.connect() as conn:
        definition = conn.execute(
            text("SELECT indexdef FROM pg_indexes WHERE indexname = 'ix_citation_document_id'")
        ).scalar_one()
    assert definition.endswith("(document_id, start_position)")

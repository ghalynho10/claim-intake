"""Alembic environment. Runs as the owner role (MIGRATE_DATABASE_URL).

The `langgraph` schema belongs to the LangGraph checkpointer, not to Alembic:
it is skipped here, otherwise autogenerate would propose dropping its tables.
"""

from alembic import context
from sqlalchemy import create_engine, pool

# Imported for their side effect: each registers its tables on Base.metadata.
import claim_intake.claims_system.models
import claim_intake.db.models  # noqa: F401
from claim_intake.config import MigrateSettings, load_or_exit
from claim_intake.db.base import Base
from claim_intake.db.urls import CHECKPOINT_SCHEMA, sqlalchemy_url
from claim_intake.logging import configure

config = context.config
target_metadata = Base.metadata

# The migrate command passes the URL in; the bare `alembic` CLI reads it from
# the environment (or .env).
url = config.attributes.get("database_url")
if url is None:
    settings = load_or_exit(MigrateSettings)
    configure(settings.log_level)
    url = settings.migrate_database_url


def include_name(name: str | None, type_: str, parent_names: object) -> bool:
    if type_ == "schema":
        return name != CHECKPOINT_SCHEMA
    return True


def include_object(
    obj: object, name: str | None, type_: str, reflected: bool, compare_to: object
) -> bool:
    # With include_schemas on, the version table reflects as schema None while
    # version_table_schema says "public", so Alembic would not recognise it.
    if type_ == "table" and name == "alembic_version":
        return False
    schema = getattr(obj, "schema", None)
    if schema is None and hasattr(obj, "table"):
        schema = getattr(obj.table, "schema", None)
    return schema != CHECKPOINT_SCHEMA


COMMON = {
    "target_metadata": target_metadata,
    "include_schemas": True,
    "include_name": include_name,
    "include_object": include_object,
    "version_table_schema": "public",
}


def run_migrations_offline() -> None:
    context.configure(
        url=sqlalchemy_url(url).render_as_string(hide_password=False),
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        **COMMON,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    engine = create_engine(sqlalchemy_url(url), poolclass=pool.NullPool)
    with engine.connect() as connection:
        context.configure(connection=connection, **COMMON)
        with context.begin_transaction():
            context.run_migrations()
    engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()

"""Idempotent cluster level setup, run as the Postgres superuser before Alembic.

Creates the roles (names and passwords come from their URLs), the target
database if it is missing, the `claims_system` and `langgraph` schemas owned by
the owner role, and the default privileges that give the app role read and
write access to whatever the owner role creates later.

Roles live at cluster level, so this cannot be an Alembic migration.

Run it alone with `python -m claim_intake.db.bootstrap`; the migrate command
runs it first.
"""

import logging
import sys

import psycopg
from psycopg import sql

from claim_intake.config import MigrateSettings, load_or_exit
from claim_intake.db.urls import database_name, password, username, with_database
from claim_intake.logging import configure

# A fixed name: under `python -m`, __name__ would be "__main__".
logger = logging.getLogger("claim_intake.db.bootstrap")

# Feature 13 gives this role a login and its read grants; until then it exists
# with no login and no privileges.
MCP_ROLE = "claim_mcp"
SCHEMAS = ("public", "claims_system", "langgraph")


class ProjectError(Exception):
    """Base for setup errors whose messages are project written (never contain a secret)."""


class BootstrapError(ProjectError):
    """A setup problem worth one clear line (never contains a secret)."""


def _diagnostic(exc: BaseException, sqlstate: str) -> str:
    """Class name and SQLSTATE only: never the exception's own text."""
    parts = [type(exc).__name__]
    if sqlstate:
        parts.append(f"SQLSTATE {sqlstate}")
    return ", ".join(parts)


def safe_error(exc: BaseException) -> str:
    """Classify failures without letting driver supplied details reach logs.

    Project errors keep their own message; everything else gets a fixed phrase
    plus the exception class name and, for driver errors, the SQLSTATE.
    """
    if isinstance(exc, ProjectError):
        return str(exc)

    driver_error: psycopg.Error | None = exc if isinstance(exc, psycopg.Error) else None
    if driver_error is None:
        original = getattr(exc, "orig", None)
        if isinstance(original, psycopg.Error):
            driver_error = original
    if driver_error is None:
        return f"operation failed ({_diagnostic(exc, '')})"

    sqlstate = driver_error.sqlstate or ""
    detail = _diagnostic(driver_error, sqlstate)
    if sqlstate.startswith("28"):
        phrase = "authentication failed"
    elif sqlstate == "42501":
        phrase = "permission denied"
    elif sqlstate == "3D000":
        phrase = "database missing"
    elif sqlstate.startswith("08") or isinstance(driver_error, psycopg.OperationalError):
        phrase = "cannot connect"
    else:
        phrase = "database operation failed"
    return f"{phrase} ({detail})"


def run(settings: MigrateSettings) -> None:
    target_db = database_name(settings.database_url)
    if database_name(settings.migrate_database_url) != target_db:
        raise BootstrapError("DATABASE_URL and MIGRATE_DATABASE_URL must name the same database")

    owner = username(settings.migrate_database_url)
    app = username(settings.database_url)
    if owner == app:
        raise BootstrapError("DATABASE_URL and MIGRATE_DATABASE_URL must use different roles")
    if MCP_ROLE in (owner, app):
        raise BootstrapError(f"the role name {MCP_ROLE} is reserved for the MCP server")

    owner_password = password(settings.migrate_database_url)
    app_password = password(settings.database_url)
    if not owner_password or not app_password:
        raise BootstrapError("DATABASE_URL and MIGRATE_DATABASE_URL must each include a password")

    with psycopg.connect(settings.admin_database_url, autocommit=True) as conn:
        _ensure_login_role(conn, owner, owner_password)
        _ensure_login_role(conn, app, app_password)
        _ensure_nologin_role(conn, MCP_ROLE)
        _ensure_database(conn, target_db, owner)

    with psycopg.connect(with_database(settings.admin_database_url, target_db)) as conn:
        _setup_schemas(conn, target_db, owner, app)
        conn.commit()

    logger.info("bootstrap complete: database %s; login roles configured", target_db)


def _role_exists(conn: psycopg.Connection, name: str) -> bool:
    return conn.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (name,)).fetchone() is not None


def _ensure_login_role(conn: psycopg.Connection, name: str, secret: str) -> None:
    verb = "ALTER" if _role_exists(conn, name) else "CREATE"
    conn.execute(
        sql.SQL("{} ROLE {} LOGIN PASSWORD {}").format(
            sql.SQL(verb), sql.Identifier(name), sql.Literal(secret)
        )
    )


def _ensure_nologin_role(conn: psycopg.Connection, name: str) -> None:
    if not _role_exists(conn, name):
        conn.execute(sql.SQL("CREATE ROLE {} NOLOGIN").format(sql.Identifier(name)))


def _ensure_database(conn: psycopg.Connection, name: str, owner: str) -> None:
    exists = conn.execute("SELECT 1 FROM pg_database WHERE datname = %s", (name,)).fetchone()
    if exists is None:
        conn.execute(
            sql.SQL("CREATE DATABASE {} OWNER {}").format(
                sql.Identifier(name), sql.Identifier(owner)
            )
        )
        logger.info("created database %s", name)


def _setup_schemas(conn: psycopg.Connection, db: str, owner: str, app: str) -> None:
    owner_id, app_id = sql.Identifier(owner), sql.Identifier(app)
    schema_ids = [sql.Identifier(s) for s in SCHEMAS]
    schema_list = sql.SQL(", ").join(schema_ids)

    conn.execute(
        sql.SQL("GRANT CONNECT ON DATABASE {} TO {}, {}").format(
            sql.Identifier(db), owner_id, app_id
        )
    )
    for schema in schema_ids:
        conn.execute(sql.SQL("CREATE SCHEMA IF NOT EXISTS {}").format(schema))
        conn.execute(sql.SQL("ALTER SCHEMA {} OWNER TO {}").format(schema, owner_id))
        conn.execute(sql.SQL("GRANT USAGE ON SCHEMA {} TO {}").format(schema, app_id))
    # Only the owner role creates objects (the default since Postgres 15, made explicit).
    conn.execute(sql.SQL("REVOKE CREATE ON SCHEMA public FROM PUBLIC"))

    # Objects the owner role creates from now on (Alembic, checkpointer setup).
    conn.execute(
        sql.SQL(
            "ALTER DEFAULT PRIVILEGES FOR ROLE {} IN SCHEMA {} "
            "GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO {}"
        ).format(owner_id, schema_list, app_id)
    )
    conn.execute(
        sql.SQL(
            "ALTER DEFAULT PRIVILEGES FOR ROLE {} IN SCHEMA {} GRANT USAGE ON SEQUENCES TO {}"
        ).format(owner_id, schema_list, app_id)
    )
    # Objects that already exist, so a rerun repairs missing grants.
    conn.execute(
        sql.SQL("GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA {} TO {}").format(
            schema_list, app_id
        )
    )
    conn.execute(
        sql.SQL("GRANT USAGE ON ALL SEQUENCES IN SCHEMA {} TO {}").format(schema_list, app_id)
    )


def main() -> None:
    settings = load_or_exit(MigrateSettings)
    configure(settings.log_level)
    try:
        run(settings)
    except (BootstrapError, psycopg.Error) as exc:
        logger.error("bootstrap failed: %s", safe_error(exc))
        sys.exit(1)


if __name__ == "__main__":
    main()

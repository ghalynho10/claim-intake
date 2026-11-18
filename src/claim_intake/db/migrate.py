"""The one shot migrate command: bootstrap, Alembic, then checkpointer setup.

`python -m claim_intake.db.migrate`, run from the directory that holds
`pyproject.toml` (the repo root, or /app in the image). Any failure exits
nonzero, so the app service never starts on a half migrated database.
"""

import logging
import sys
from pathlib import Path

import psycopg
from alembic import command
from alembic.config import Config as AlembicConfig
from alembic.util import CommandError
from langgraph.checkpoint.postgres import PostgresSaver
from psycopg.rows import dict_row
from sqlalchemy.exc import SQLAlchemyError

from claim_intake.config import MigrateSettings, load_or_exit
from claim_intake.db import bootstrap
from claim_intake.db.bootstrap import BootstrapError, safe_error
from claim_intake.db.urls import CHECKPOINT_SCHEMA, checkpointer_conninfo
from claim_intake.logging import configure

# A fixed name: under `python -m`, __name__ would be "__main__".
logger = logging.getLogger("claim_intake.db.migrate")


class MigrateError(Exception):
    """A migrate problem worth one clear line (never contains a secret)."""


def run(settings: MigrateSettings, pyproject: Path | None = None) -> None:
    bootstrap.run(settings)
    upgrade(settings, pyproject)
    setup_checkpointer(settings)
    logger.info("migrate complete")


def upgrade(settings: MigrateSettings, pyproject: Path | None = None) -> None:
    """`alembic upgrade head` as the owner role."""
    pyproject = pyproject or Path.cwd() / "pyproject.toml"
    if not pyproject.is_file():
        raise MigrateError(f"no pyproject.toml in {pyproject.parent}; run from the project root")
    config = AlembicConfig(toml_file=pyproject)
    config.set_main_option("script_location", str(pyproject.parent / "migrations"))
    config.attributes["database_url"] = settings.migrate_database_url
    command.upgrade(config, "head")
    logger.info("alembic upgrade head complete")


def setup_checkpointer(settings: MigrateSettings) -> None:
    """Create LangGraph's checkpoint tables in their own schema, as the owner role."""
    conninfo = checkpointer_conninfo(settings.migrate_database_url)
    with psycopg.connect(
        conninfo, autocommit=True, prepare_threshold=0, row_factory=dict_row
    ) as conn:
        PostgresSaver(conn).setup()
        row = conn.execute(
            "SELECT to_regclass(%s) IS NOT NULL AS ok", (f"{CHECKPOINT_SCHEMA}.checkpoints",)
        ).fetchone()
    if not row or not row["ok"]:
        raise MigrateError(f"checkpoint tables did not land in schema {CHECKPOINT_SCHEMA}")
    logger.info("checkpointer setup complete in schema %s", CHECKPOINT_SCHEMA)


def main() -> None:
    settings = load_or_exit(MigrateSettings)
    configure(settings.log_level)
    try:
        run(settings)
    except (BootstrapError, MigrateError, CommandError, SQLAlchemyError, psycopg.Error) as exc:
        logger.error("migrate failed: %s", safe_error(exc))
        sys.exit(1)


if __name__ == "__main__":
    main()

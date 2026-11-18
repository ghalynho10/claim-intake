"""The SQLAlchemy engine and the database health probe."""

from sqlalchemy import Engine, create_engine, text

from claim_intake.db.urls import sqlalchemy_url

# Applies to opening a connection. Postgres runs next to the app, so two
# seconds is generous and keeps /health quick when the database is down.
CONNECT_TIMEOUT_SECONDS = 2
HEALTH_STATEMENT_TIMEOUT_MS = 2000


def make_engine(database_url: str) -> Engine:
    return create_engine(
        sqlalchemy_url(database_url),
        pool_pre_ping=True,
        connect_args={"connect_timeout": CONNECT_TIMEOUT_SECONDS},
    )


def ping(engine: Engine) -> None:
    """Run `SELECT 1` with a short statement timeout. Raises on any failure."""
    with engine.connect() as conn:
        conn.execute(text(f"SET LOCAL statement_timeout = {HEALTH_STATEMENT_TIMEOUT_MS}"))
        conn.execute(text("SELECT 1"))

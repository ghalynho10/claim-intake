"""Turn the stored `postgresql://` URLs into what each library expects."""

from psycopg.conninfo import make_conninfo
from sqlalchemy.engine import URL, make_url

CHECKPOINT_SCHEMA = "langgraph"


def sqlalchemy_url(url: str) -> URL:
    """SQLAlchemy form. A bare `postgresql://` would pick psycopg2."""
    return make_url(url).set(drivername="postgresql+psycopg")


def with_database(url: str, database: str) -> str:
    """The same server and credentials, pointed at another database."""
    return make_url(url).set(database=database).render_as_string(hide_password=False)


def database_name(url: str) -> str:
    name = make_url(url).database
    if not name:
        raise ValueError("database URL has no database name")
    return name


def username(url: str) -> str:
    name = make_url(url).username
    if not name:
        raise ValueError("database URL has no user name")
    return name


def password(url: str) -> str | None:
    secret = make_url(url).password
    return None if secret is None else str(secret)


def checkpointer_conninfo(url: str) -> str:
    """psycopg conninfo whose `search_path` puts LangGraph's tables in their schema."""
    return make_conninfo(url, options=f"-c search_path={CHECKPOINT_SCHEMA}")

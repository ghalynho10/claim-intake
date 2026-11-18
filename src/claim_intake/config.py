"""Typed settings read from the environment (and a local, uncommitted `.env`).

Two classes keep credentials apart:

* `Settings` is what the app process holds: the `claim_app` URL and the log level.
* `MigrateSettings` is what the one shot migrate job holds: the owner and
  superuser URLs as well. The app never loads it.

Real environment variables win over `.env`. Each tunable setting arrives with the
feature that first uses it; none exist yet.
"""

import sys
from typing import Annotated, Literal

from pydantic import AfterValidator, ValidationError
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import make_url
from sqlalchemy.exc import ArgumentError


def _check_postgres_url(value: str) -> str:
    # Never echo the value in an error: URLs carry passwords.
    try:
        url = make_url(value)
    except ArgumentError:
        raise ValueError("is not a valid database URL") from None
    if url.drivername != "postgresql":
        raise ValueError("must start with postgresql:// (no driver suffix)")
    if not url.host or not url.database or not url.username:
        raise ValueError("must include a user, a host and a database name")
    return value


PostgresUrl = Annotated[str, AfterValidator(_check_postgres_url)]
LogLevel = Literal["DEBUG", "INFO", "WARNING", "ERROR"]

_COMMON = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")


class Settings(BaseSettings):
    """Settings for the app process."""

    model_config = _COMMON

    database_url: PostgresUrl
    log_level: LogLevel = "INFO"


class MigrateSettings(BaseSettings):
    """Settings for the migrate job: bootstrap, Alembic, checkpointer setup."""

    model_config = _COMMON

    # The claim_app URL: bootstrap takes that role's name and password from it.
    database_url: PostgresUrl
    migrate_database_url: PostgresUrl
    admin_database_url: PostgresUrl
    log_level: LogLevel = "INFO"


def load_or_exit[T: BaseSettings](cls: type[T]) -> T:
    """Build settings, or print one line per bad setting and exit 1.

    The lines name the variable and the problem, never the value.
    """
    try:
        return cls()
    except ValidationError as exc:
        for err in exc.errors(include_input=False, include_url=False):
            name = ".".join(str(part) for part in err["loc"]).upper()
            message = err["msg"].removeprefix("Value error, ")
            print(f"config error: {name}: {message}", file=sys.stderr)
        sys.exit(1)

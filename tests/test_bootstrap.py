"""Regression tests keep database connection details out of bootstrap logs."""

import logging
import secrets

import psycopg
import pytest
from sqlalchemy.engine import URL, make_url

from claim_intake.config import MigrateSettings
from claim_intake.db import bootstrap, migrate
from claim_intake.db.urls import username
from claim_intake.logging import configure


def _url(login: str, secret: str, host: str, port: int, database: str) -> str:
    return URL.create(
        "postgresql",
        username=login,
        password=secret,
        host=host,
        port=port,
        database=database,
        query={"connect_timeout": "1"},
    ).render_as_string(hide_password=False)


def _assert_no_connection_details(message: str, details: tuple[str, ...]) -> None:
    if any(detail in message for detail in details):
        pytest.fail("log exposed connection details", pytrace=False)


def _assert_safe_message(message: str, expected: str) -> None:
    if expected not in message:
        classifications = (
            "authentication failed",
            "cannot connect",
            "permission denied",
            "database missing",
            "database operation failed",
            "operation failed",
        )
        actual = next((item for item in classifications if item in message), "unclassified")
        pytest.fail(f"log used safe error classification: {actual}", pytrace=False)


def test_unreachable_connection_log_omits_connection_details(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    host = f"{secrets.token_hex(6)}.invalid"
    port = 65432
    database = f"db_{secrets.token_hex(4)}"
    app_login = f"app_{secrets.token_hex(4)}"
    owner_login = f"owner_{secrets.token_hex(4)}"
    admin_login = f"admin_{secrets.token_hex(4)}"
    app_password = secrets.token_hex(8)
    owner_password = secrets.token_hex(8)
    admin_password = secrets.token_hex(8)
    settings = MigrateSettings(
        _env_file=None,
        database_url=_url(app_login, app_password, host, port, database),
        migrate_database_url=_url(owner_login, owner_password, host, port, database),
        admin_database_url=_url(admin_login, admin_password, host, port, "postgres"),
        log_level="INFO",
    )
    details = (
        host,
        str(port),
        app_login,
        owner_login,
        admin_login,
        app_password,
        owner_password,
        admin_password,
    )
    monkeypatch.setattr(bootstrap, "load_or_exit", lambda _settings_type: settings)

    with pytest.raises(SystemExit) as raised:
        bootstrap.main()

    assert raised.value.code == 1
    message = capsys.readouterr().err
    _assert_safe_message(message, "bootstrap failed: cannot connect")
    _assert_no_connection_details(message, details)


def test_server_rejection_log_omits_connection_details(
    migrate_settings: MigrateSettings,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    configure("INFO")
    bootstrap.run(migrate_settings)
    capsys.readouterr()

    admin_url = make_url(migrate_settings.admin_database_url)
    blocked_password = secrets.token_hex(8)
    blocked_url = (
        admin_url.set(username=bootstrap.MCP_ROLE, password=blocked_password)
        .update_query_dict({"connect_timeout": "1"})
        .render_as_string(hide_password=False)
    )
    settings = MigrateSettings(
        _env_file=None,
        database_url=migrate_settings.database_url,
        migrate_database_url=migrate_settings.migrate_database_url,
        admin_database_url=blocked_url,
        log_level="INFO",
    )
    details = tuple(
        detail
        for detail in (
            admin_url.host,
            str(admin_url.port) if admin_url.port is not None else None,
            bootstrap.MCP_ROLE,
            blocked_password,
        )
        if detail is not None
    )
    monkeypatch.setattr(migrate, "load_or_exit", lambda _settings_type: settings)

    with pytest.raises(SystemExit) as raised:
        migrate.main()

    assert raised.value.code == 1
    message = capsys.readouterr().err
    _assert_safe_message(message, "migrate failed: cannot connect")
    _assert_no_connection_details(message, details)


def test_success_log_omits_role_names(
    migrate_settings: MigrateSettings, caplog: pytest.LogCaptureFixture
) -> None:
    owner = username(migrate_settings.migrate_database_url)
    app = username(migrate_settings.database_url)

    with caplog.at_level(logging.INFO, logger="claim_intake.db.bootstrap"):
        bootstrap.run(migrate_settings)

    messages = "\n".join(record.getMessage() for record in caplog.records)
    assert "login roles configured" in messages
    _assert_no_connection_details(messages, (owner, app))


def test_project_errors_keep_their_own_message() -> None:
    message = "no pyproject.toml here; run from the project root"
    assert bootstrap.safe_error(migrate.MigrateError(message)) == message
    assert bootstrap.safe_error(bootstrap.BootstrapError(message)) == message


def test_driver_error_keeps_class_name_and_sqlstate_but_no_details() -> None:
    host = f"{secrets.token_hex(6)}.invalid"
    login = f"user_{secrets.token_hex(4)}"
    secret = secrets.token_hex(8)
    port = "65432"
    detail = f'connection to server at "{host}", port {port} failed for "{login}" ({secret})'
    exc = psycopg.errors.UndefinedTable(detail)

    message = bootstrap.safe_error(exc)

    assert message == "database operation failed (UndefinedTable, SQLSTATE 42P01)"
    _assert_no_connection_details(message, (host, port, login, secret))


def test_connection_error_without_sqlstate_names_only_its_class() -> None:
    exc = psycopg.OperationalError(f"could not translate host {secrets.token_hex(6)}.invalid")

    assert bootstrap.safe_error(exc) == "cannot connect (OperationalError)"


def test_unknown_error_names_only_its_class() -> None:
    assert bootstrap.safe_error(ValueError(secrets.token_hex(8))) == "operation failed (ValueError)"

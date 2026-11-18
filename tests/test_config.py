"""Config loads and validates at startup, and fails clearly on a bad value."""

import secrets
from pathlib import Path

import pytest

from claim_intake.api.app import create_app
from claim_intake.config import MigrateSettings, Settings, load_or_exit

SECRET = secrets.token_hex(8)


@pytest.fixture(autouse=True)
def isolated_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    # No .env in the working directory, and none of the real variables.
    monkeypatch.chdir(tmp_path)
    for name in ("DATABASE_URL", "MIGRATE_DATABASE_URL", "ADMIN_DATABASE_URL", "LOG_LEVEL"):
        monkeypatch.delenv(name, raising=False)


def test_valid_settings_load(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", f"postgresql://claim_app:{SECRET}@db:5432/claim_intake")
    settings = load_or_exit(Settings)
    assert settings.log_level == "INFO"


def test_bad_values_exit_1_naming_each_setting_without_its_value(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("DATABASE_URL", f"mysql://claim_app:{SECRET}@db:3306/claim_intake")
    monkeypatch.setenv("LOG_LEVEL", "LOUD")

    with pytest.raises(SystemExit) as exit_info:
        create_app()

    assert exit_info.value.code == 1
    err = capsys.readouterr().err
    lines = err.strip().splitlines()
    assert len(lines) == 2
    assert any(line.startswith("config error: DATABASE_URL: ") for line in lines)
    assert any(line.startswith("config error: LOG_LEVEL: ") for line in lines)
    assert SECRET not in err
    assert "LOUD" not in err


def test_missing_required_setting_is_named(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exit_info:
        load_or_exit(Settings)
    assert exit_info.value.code == 1
    assert capsys.readouterr().err.strip() == "config error: DATABASE_URL: Field required"


@pytest.mark.parametrize(
    "url",
    [
        "not a url",
        "postgresql+psycopg://claim_app:x@db:5432/claim_intake",  # driver suffix not allowed
        "postgresql://claim_app:x@db:5432",  # no database
    ],
)
def test_malformed_database_urls_are_rejected(
    url: str, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("DATABASE_URL", url)
    with pytest.raises(SystemExit):
        load_or_exit(Settings)
    err = capsys.readouterr().err
    assert err.startswith("config error: DATABASE_URL: ")
    assert url not in err


def test_app_settings_never_hold_owner_or_superuser_urls() -> None:
    assert "migrate_database_url" not in Settings.model_fields
    assert "admin_database_url" not in Settings.model_fields
    assert {"migrate_database_url", "admin_database_url"} <= MigrateSettings.model_fields.keys()

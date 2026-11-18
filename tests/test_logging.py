"""Logs are JSON lines on stderr carrying the request id and claim id."""

import json
import logging
from collections.abc import Iterator

import pytest

from claim_intake.logging import QuietPathsFilter, claim_id_var, configure, request_id_var


@pytest.fixture(autouse=True)
def restore_logging() -> Iterator[None]:
    yield
    configure("WARNING")


def test_log_line_is_json_on_stderr_with_context(capsys: pytest.CaptureFixture[str]) -> None:
    configure("INFO")
    rid, cid = request_id_var.set("req-1"), claim_id_var.set("claim-9")
    try:
        logging.getLogger("claim_intake.test").info("hello %s", "world")
    finally:
        request_id_var.reset(rid)
        claim_id_var.reset(cid)

    captured = capsys.readouterr()
    assert captured.out == ""
    entry = json.loads(captured.err.strip().splitlines()[-1])
    assert entry["msg"] == "hello world"
    assert entry["level"] == "INFO"
    assert entry["logger"] == "claim_intake.test"
    assert entry["request_id"] == "req-1"
    assert entry["claim_id"] == "claim-9"
    assert entry["exc"] is None
    assert entry["ts"].endswith("+00:00")


def test_exception_is_logged_in_exc_field(capsys: pytest.CaptureFixture[str]) -> None:
    configure("INFO")
    try:
        raise RuntimeError("boom")
    except RuntimeError:
        logging.getLogger("claim_intake.test").exception("failed")
    entry = json.loads(capsys.readouterr().err.strip().splitlines()[-1])
    assert "RuntimeError: boom" in entry["exc"]


def _access_record(path: str) -> logging.LogRecord:
    return logging.LogRecord(
        "uvicorn.access",
        logging.INFO,
        __file__,
        0,
        '%s - "%s %s HTTP/%s" %d',
        ("127.0.0.1:5000", "GET", path, "1.1", 200),
        None,
    )


def test_health_requests_stay_out_of_access_log() -> None:
    quiet = QuietPathsFilter()
    assert quiet.filter(_access_record("/health")) is False
    assert quiet.filter(_access_record("/health?probe=1")) is False
    assert quiet.filter(_access_record("/api/claims")) is True

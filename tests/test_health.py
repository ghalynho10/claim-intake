"""`/health` and the request id header."""

from fastapi.testclient import TestClient

from claim_intake import __version__
from claim_intake.api.app import create_app
from claim_intake.config import Settings


def test_health_ok_when_database_reachable(client: TestClient) -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "version": __version__}


def test_health_503_without_detail_when_database_unreachable() -> None:
    # Port 1 refuses connections, so this fails fast.
    settings = Settings(
        _env_file=None,
        database_url="postgresql://claim_app:pw@127.0.0.1:1/claim_intake_test",
        log_level="ERROR",
    )
    with TestClient(create_app(settings)) as client:
        response = client.get("/health")
    assert response.status_code == 503
    assert response.json() == {"status": "unavailable", "version": __version__}


def test_valid_inbound_request_id_is_echoed(client: TestClient) -> None:
    response = client.get("/health", headers={"X-Request-ID": "abc-123"})
    assert response.headers["X-Request-ID"] == "abc-123"


def test_invalid_inbound_request_id_is_replaced(client: TestClient) -> None:
    for bad in ("has spaces", "x" * 65, "semi;colon"):
        response = client.get("/health", headers={"X-Request-ID": bad})
        echoed = response.headers["X-Request-ID"]
        assert echoed != bad
        assert len(echoed) == 32 and echoed.isalnum()


def test_request_id_generated_when_absent(client: TestClient) -> None:
    first = client.get("/health").headers["X-Request-ID"]
    second = client.get("/health").headers["X-Request-ID"]
    assert first != second

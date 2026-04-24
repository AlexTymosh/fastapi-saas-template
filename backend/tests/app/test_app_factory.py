from fastapi.testclient import TestClient

from app.main import create_app
from tests.helpers.settings import reset_settings_cache


def test_create_app_uses_configured_api_prefix(monkeypatch) -> None:
    monkeypatch.setenv("API__V1_PREFIX", "/api/custom-v1")
    reset_settings_cache()

    app = create_app()
    client = TestClient(app)

    response = client.get("/api/custom-v1/health/live")

    assert response.status_code == 200

    reset_settings_cache()


def test_create_app_uses_configured_request_id_header(monkeypatch) -> None:
    monkeypatch.setenv("REQUEST_CONTEXT__HEADER_NAME", "X-Correlation-ID")
    reset_settings_cache()

    app = create_app()
    client = TestClient(app)

    response = client.get("/api/v1/health/live")

    assert response.status_code == 200
    assert "x-correlation-id" in response.headers

    reset_settings_cache()

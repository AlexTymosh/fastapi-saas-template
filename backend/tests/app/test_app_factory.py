from fastapi.testclient import TestClient

from app.core.config.settings import get_settings
from app.main import create_app


def test_create_app_uses_configured_api_prefix(monkeypatch) -> None:
    monkeypatch.setenv("API__V1_PREFIX", "/api/custom-v1")
    get_settings.cache_clear()

    app = create_app()
    client = TestClient(app)

    response = client.get("/api/custom-v1/health/live")

    assert response.status_code == 200

    get_settings.cache_clear()


def test_create_app_uses_configured_request_id_header(monkeypatch) -> None:
    monkeypatch.setenv("REQUEST_CONTEXT__HEADER_NAME", "X-Correlation-ID")
    get_settings.cache_clear()

    app = create_app()
    client = TestClient(app)

    response = client.get("/api/v1/health/live")

    assert response.status_code == 200
    assert "x-correlation-id" in response.headers

    get_settings.cache_clear()

from fastapi.testclient import TestClient

from app.core.config.settings import Settings
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


def test_create_app_accepts_explicit_settings_injection() -> None:
    settings = Settings(
        api={"v1_prefix": "/api/injected-v1"},
    )

    app = create_app(settings=settings)
    client = TestClient(app)

    response = client.get("/api/injected-v1/health/live")

    assert response.status_code == 200


def test_create_app_repeated_instantiation_respects_cache_reset(monkeypatch) -> None:
    monkeypatch.setenv("API__V1_PREFIX", "/api/first-v1")
    reset_settings_cache()
    first_app = create_app()
    first_client = TestClient(first_app)

    first_response = first_client.get("/api/first-v1/health/live")
    assert first_response.status_code == 200

    monkeypatch.setenv("API__V1_PREFIX", "/api/second-v1")
    reset_settings_cache()
    second_app = create_app()
    second_client = TestClient(second_app)

    second_response = second_client.get("/api/second-v1/health/live")
    assert second_response.status_code == 200

    first_app_after_change = first_client.get("/api/first-v1/health/live")
    assert first_app_after_change.status_code == 200
    assert first_client.get("/api/second-v1/health/live").status_code == 404
    assert second_client.get("/api/first-v1/health/live").status_code == 404

    reset_settings_cache()

from fastapi.testclient import TestClient

import app.main as main_module
from app.core.config.settings import Settings
from app.main import create_app
from tests.helpers.asyncio_runner import run_async
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


def test_create_app_uses_custom_request_id_header_end_to_end(monkeypatch) -> None:
    monkeypatch.setenv("REQUEST_CONTEXT__HEADER_NAME", "X-Correlation-ID")
    reset_settings_cache()

    app = create_app()
    client = TestClient(app)

    success_response = client.get("/api/v1/health/live")

    assert success_response.status_code == 200
    assert "x-correlation-id" in success_response.headers
    assert success_response.headers["x-correlation-id"] != ""
    assert "x-request-id" not in success_response.headers

    error_response = client.get("/missing-route")

    assert error_response.status_code == 404
    assert error_response.headers["content-type"].startswith("application/problem+json")
    assert "x-correlation-id" in error_response.headers
    assert "x-request-id" not in error_response.headers

    problem_body = error_response.json()
    assert "request_id" in problem_body
    assert error_response.headers["x-correlation-id"] == problem_body["request_id"]

    reset_settings_cache()


def test_create_app_trusts_incoming_custom_request_id_header(monkeypatch) -> None:
    monkeypatch.setenv("REQUEST_CONTEXT__HEADER_NAME", "X-Correlation-ID")
    reset_settings_cache()

    try:
        app = create_app()
        client = TestClient(app)

        incoming_request_id = "corr-123"

        success_response = client.get(
            "/api/v1/health/live",
            headers={"X-Correlation-ID": incoming_request_id},
        )

        assert success_response.status_code == 200
        assert success_response.headers["x-correlation-id"] == incoming_request_id
        assert "x-request-id" not in success_response.headers

        error_response = client.get(
            "/missing-route",
            headers={"X-Correlation-ID": incoming_request_id},
        )

        assert error_response.status_code == 404
        assert error_response.headers["content-type"].startswith(
            "application/problem+json"
        )
        assert error_response.headers["x-correlation-id"] == incoming_request_id
        assert "x-request-id" not in error_response.headers
        assert error_response.json()["request_id"] == incoming_request_id
    finally:
        reset_settings_cache()


def test_create_app_is_deterministic_across_repeated_env_changes(monkeypatch) -> None:
    monkeypatch.setenv("API__V1_PREFIX", "/api/first-v1")
    reset_settings_cache()

    first_app = create_app()
    first_client = TestClient(first_app)
    first_response = first_client.get("/api/first-v1/health/live")

    assert first_response.status_code == 200
    assert first_client.get("/api/second-v1/health/live").status_code == 404

    monkeypatch.setenv("API__V1_PREFIX", "/api/second-v1")
    reset_settings_cache()

    second_app = create_app()
    second_client = TestClient(second_app)
    second_response = second_client.get("/api/second-v1/health/live")

    assert second_response.status_code == 200
    assert second_client.get("/api/first-v1/health/live").status_code == 404
    assert first_client.get("/api/first-v1/health/live").status_code == 200

    reset_settings_cache()


def test_create_app_accepts_explicit_settings_injection() -> None:
    settings = Settings(
        api={"v1_prefix": "/api/injected-v1"},
    )

    app = create_app(settings=settings)
    client = TestClient(app)

    response = client.get("/api/injected-v1/health/live")

    assert response.status_code == 200


def test_create_app_settings_injection_is_used_by_lifespan(monkeypatch) -> None:
    settings = Settings(
        api={"v1_prefix": "/api/injected-lifespan-v1"},
    )
    app = create_app(settings=settings)
    auth_validation_calls: list[Settings] = []

    async def fake_init_auth_validation(received_settings: Settings) -> None:
        auth_validation_calls.append(received_settings)

    async def noop(*args, **kwargs) -> None:
        _ = args, kwargs

    def fail_get_settings() -> Settings:
        raise AssertionError("lifespan must use app.state.settings")

    monkeypatch.setattr(main_module, "get_settings", fail_get_settings)
    monkeypatch.setattr(main_module, "init_auth_validation", fake_init_auth_validation)
    monkeypatch.setattr(main_module, "init_observability", noop)
    monkeypatch.setattr(main_module, "init_rate_limiter", noop)
    monkeypatch.setattr(main_module, "shutdown_rate_limiter", noop)
    monkeypatch.setattr(main_module, "close_redis", noop)
    monkeypatch.setattr(main_module, "dispose_engine", noop)
    monkeypatch.setattr(main_module, "shutdown_observability", noop)

    async def run_lifespan() -> None:
        async with app.router.lifespan_context(app):
            pass

    assert app.state.settings is settings
    run_async(run_lifespan())
    assert auth_validation_calls == [settings]

from fastapi.testclient import TestClient

from app.core.config.settings import Settings
from app.main import create_app


def _client_with_cors(
    *,
    enabled: bool,
    allow_origins: list[str] | None = None,
) -> TestClient:
    settings = Settings(
        cors={
            "enabled": enabled,
            "allow_origins": allow_origins or [],
        }
    )
    return TestClient(create_app(settings=settings))


def test_cors_disabled_does_not_add_cors_headers() -> None:
    with _client_with_cors(enabled=False) as client:
        response = client.get(
            "/api/v1/health/live",
            headers={"Origin": "http://localhost:3000"},
        )

    assert response.status_code == 200
    assert "access-control-allow-origin" not in response.headers
    assert "access-control-expose-headers" not in response.headers


def test_cors_allowed_origin_preflight_returns_expected_headers() -> None:
    with _client_with_cors(
        enabled=True,
        allow_origins=["http://localhost:3000", "http://localhost:5173"],
    ) as client:
        response = client.options(
            "/api/v1/health/live",
            headers={
                "Origin": "http://localhost:3000",
                "Access-Control-Request-Method": "GET",
                "Access-Control-Request-Headers": "Authorization, X-Request-ID",
            },
        )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://localhost:3000"
    assert "GET" in response.headers["access-control-allow-methods"]
    assert "Authorization" in response.headers["access-control-allow-headers"]
    assert "X-Request-ID" in response.headers["access-control-allow-headers"]
    assert response.headers["access-control-max-age"] == "600"


def test_cors_allowed_response_exposes_operational_headers() -> None:
    with _client_with_cors(
        enabled=True,
        allow_origins=["http://localhost:3000"],
    ) as client:
        response = client.get(
            "/api/v1/health/live",
            headers={"Origin": "http://localhost:3000"},
        )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://localhost:3000"
    exposed_headers = response.headers["access-control-expose-headers"]
    assert "X-Request-ID" in exposed_headers
    assert "Retry-After" in exposed_headers


def test_cors_disallowed_origin_does_not_receive_permissive_headers() -> None:
    with _client_with_cors(
        enabled=True,
        allow_origins=["http://localhost:3000"],
    ) as client:
        response = client.options(
            "/api/v1/health/live",
            headers={
                "Origin": "https://evil.example",
                "Access-Control-Request-Method": "GET",
            },
        )

    assert response.status_code == 400
    assert "access-control-allow-origin" not in response.headers

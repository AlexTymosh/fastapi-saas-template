from fastapi.testclient import TestClient

from app.core.config.settings import CorsSettings, Settings
from app.main import create_app

ALLOWED_ORIGIN = "http://localhost:3000"
DISALLOWED_ORIGIN = "http://malicious.localhost:3000"


def _client_with_cors(cors: CorsSettings) -> TestClient:
    settings = Settings(cors=cors)
    return TestClient(create_app(settings=settings))


def test_cors_headers_are_not_added_when_disabled() -> None:
    with _client_with_cors(CorsSettings(enabled=False)) as client:
        response = client.get(
            "/api/v1/health/live",
            headers={"Origin": ALLOWED_ORIGIN},
        )

    assert response.status_code == 200
    assert "access-control-allow-origin" not in response.headers
    assert "access-control-expose-headers" not in response.headers


def test_cors_preflight_allows_configured_origin() -> None:
    with _client_with_cors(
        CorsSettings(enabled=True, allow_origins=[ALLOWED_ORIGIN])
    ) as client:
        response = client.options(
            "/api/v1/health/live",
            headers={
                "Origin": ALLOWED_ORIGIN,
                "Access-Control-Request-Method": "GET",
                "Access-Control-Request-Headers": "Authorization, X-Request-ID",
            },
        )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == ALLOWED_ORIGIN
    assert "GET" in response.headers["access-control-allow-methods"]
    assert "Authorization" in response.headers["access-control-allow-headers"]
    assert "X-Request-ID" in response.headers["access-control-allow-headers"]
    assert response.headers["access-control-max-age"] == "600"


def test_cors_simple_response_exposes_request_and_retry_headers() -> None:
    with _client_with_cors(
        CorsSettings(enabled=True, allow_origins=[ALLOWED_ORIGIN])
    ) as client:
        response = client.get(
            "/api/v1/health/live",
            headers={"Origin": ALLOWED_ORIGIN},
        )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == ALLOWED_ORIGIN
    assert response.headers["access-control-expose-headers"] == (
        "X-Request-ID, Retry-After"
    )


def test_disallowed_origin_does_not_receive_permissive_cors_headers() -> None:
    with _client_with_cors(
        CorsSettings(enabled=True, allow_origins=[ALLOWED_ORIGIN])
    ) as client:
        simple_response = client.get(
            "/api/v1/health/live",
            headers={"Origin": DISALLOWED_ORIGIN},
        )
        preflight_response = client.options(
            "/api/v1/health/live",
            headers={
                "Origin": DISALLOWED_ORIGIN,
                "Access-Control-Request-Method": "GET",
            },
        )

    assert simple_response.status_code == 200
    assert "access-control-allow-origin" not in simple_response.headers
    assert preflight_response.status_code == 400
    assert "access-control-allow-origin" not in preflight_response.headers

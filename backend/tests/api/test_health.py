from fastapi.testclient import TestClient

from app.core.config.settings import get_settings
from app.main import create_app


def _build_client(
    monkeypatch,
    *,
    database_url: str = "",
    redis_url: str = "",
) -> TestClient:
    monkeypatch.setenv("DATABASE__URL", database_url)
    monkeypatch.setenv("REDIS__URL", redis_url)
    get_settings.cache_clear()

    app = create_app()
    return TestClient(app)


def test_health_live_returns_200_and_ok_status(client: TestClient) -> None:
    url = client.app.url_path_for("health_live")
    response = client.get(url)

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    assert "x-request-id" in response.headers
    assert response.headers["x-request-id"] != ""


def test_health_ready_returns_200_with_no_configured_dependencies(
    monkeypatch,
) -> None:
    with _build_client(
        monkeypatch,
        database_url="",
        redis_url="",
    ) as client:
        url = client.app.url_path_for("health_ready")
        response = client.get(url)

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "services": {},
    }


def test_health_ready_returns_200_when_postgresql_is_available(
    monkeypatch,
) -> None:
    async def fake_ping_postgresql() -> None:
        return None

    monkeypatch.setattr("app.services.health._ping_postgresql", fake_ping_postgresql)

    with _build_client(
        monkeypatch,
        database_url="postgresql+psycopg://app:app@localhost:5432/fastapi_saas_template",
        redis_url="",
    ) as client:
        url = client.app.url_path_for("health_ready")
        response = client.get(url)

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "services": {
            "postgresql": "ok",
        },
    }


def test_health_ready_returns_503_when_postgresql_is_unavailable(
    monkeypatch,
) -> None:
    async def fake_ping_postgresql() -> None:
        raise RuntimeError("database is down")

    monkeypatch.setattr("app.services.health._ping_postgresql", fake_ping_postgresql)

    with _build_client(
        monkeypatch,
        database_url="postgresql+psycopg://app:app@localhost:5432/fastapi_saas_template",
        redis_url="",
    ) as client:
        url = client.app.url_path_for("health_ready")
        response = client.get(url)

    assert response.status_code == 503
    assert response.json() == {
        "status": "unavailable",
        "services": {
            "postgresql": "unavailable",
        },
    }

from fastapi.testclient import TestClient


def test_health_live_returns_200_and_ok_status(client: TestClient) -> None:
    url = client.app.url_path_for("health_live")
    response = client.get(url)

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    assert "x-request-id" in response.headers
    assert response.headers["x-request-id"] != ""


def test_health_ready_returns_503_when_database_is_not_configured(
    client_factory,
) -> None:
    with client_factory(database_url=None, redis_url=None) as client:
        url = client.app.url_path_for("health_ready")
        response = client.get(url)

    assert response.status_code == 503
    assert response.json() == {
        "status": "unavailable",
        "services": {
            "postgresql": "unavailable",
        },
    }


def test_health_ready_returns_200_when_postgresql_is_available(
    monkeypatch,
    client_factory,
) -> None:
    async def fake_ping_postgresql() -> None:
        return None

    monkeypatch.setattr(
        "app.health.services.health._ping_postgresql", fake_ping_postgresql
    )

    with client_factory(
        database_url="postgresql+psycopg://user:pass@test/test_db",
        redis_url=None,
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
    client_factory,
) -> None:
    async def fake_ping_postgresql() -> None:
        raise RuntimeError("database is down")

    monkeypatch.setattr(
        "app.health.services.health._ping_postgresql", fake_ping_postgresql
    )

    with client_factory(
        database_url="postgresql+psycopg://user:pass@test/test_db",
        redis_url=None,
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


def test_health_ready_returns_200_when_redis_is_available(
    monkeypatch,
    client_factory,
) -> None:
    async def fake_ping_postgresql() -> None:
        return None

    async def fake_ping_redis() -> None:
        return None

    monkeypatch.setattr(
        "app.health.services.health._ping_postgresql", fake_ping_postgresql
    )
    monkeypatch.setattr("app.health.services.health._ping_redis", fake_ping_redis)

    with client_factory(
        database_url="postgresql+psycopg://user:pass@test/test_db",
        redis_url="redis://test:6379/0",
    ) as client:
        url = client.app.url_path_for("health_ready")
        response = client.get(url)

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "services": {
            "postgresql": "ok",
            "redis": "ok",
        },
    }


def test_health_ready_returns_503_when_redis_is_unavailable(
    monkeypatch,
    client_factory,
) -> None:
    async def fake_ping_postgresql() -> None:
        return None

    async def fake_ping_redis() -> None:
        raise RuntimeError("redis is down")

    monkeypatch.setattr(
        "app.health.services.health._ping_postgresql", fake_ping_postgresql
    )
    monkeypatch.setattr("app.health.services.health._ping_redis", fake_ping_redis)

    with client_factory(
        database_url="postgresql+psycopg://user:pass@test/test_db",
        redis_url="redis://test:6379/0",
    ) as client:
        url = client.app.url_path_for("health_ready")
        response = client.get(url)

    assert response.status_code == 503
    assert response.json() == {
        "status": "unavailable",
        "services": {
            "postgresql": "ok",
            "redis": "unavailable",
        },
    }


def test_health_ready_returns_503_when_database_url_is_blank(
    client_factory,
) -> None:
    with client_factory(
        database_url="   ",
        redis_url=None,
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


def test_health_ready_returns_503_when_one_configured_dependency_is_unavailable(
    monkeypatch,
    client_factory,
) -> None:
    async def fake_ping_postgresql() -> None:
        return None

    async def fake_ping_redis() -> None:
        raise RuntimeError("redis is down")

    monkeypatch.setattr(
        "app.health.services.health._ping_postgresql", fake_ping_postgresql
    )
    monkeypatch.setattr("app.health.services.health._ping_redis", fake_ping_redis)

    with client_factory(
        database_url="postgresql+psycopg://user:pass@test/test_db",
        redis_url="redis://test:6379/0",
    ) as client:
        url = client.app.url_path_for("health_ready")
        response = client.get(url)

    assert response.status_code == 503
    assert response.json() == {
        "status": "unavailable",
        "services": {
            "postgresql": "ok",
            "redis": "unavailable",
        },
    }


def test_health_endpoints_are_not_rate_limited(monkeypatch, client_factory) -> None:
    class BlockingLimiter:
        async def hit(self, item, key: str) -> bool:
            return False

        async def get_window_stats(self, item, key: str):
            raise AssertionError("health endpoints must not use limiter")

    async def _setup(app, settings) -> None:
        runtime_type = type("Runtime", (), {"limiter": BlockingLimiter()})
        app.state.rate_limit_runtime = runtime_type()

    async def _teardown(app) -> None:
        app.state.rate_limit_runtime = None

    monkeypatch.setattr("app.main.setup_rate_limiter", _setup)
    monkeypatch.setattr("app.main.teardown_rate_limiter", _teardown)
    monkeypatch.setenv("RATE_LIMITING__ENABLED", "true")
    monkeypatch.setenv("REDIS__URL", "redis://placeholder:6379/0")

    with client_factory(
        database_url=None,
        redis_url="redis://placeholder:6379/0",
    ) as client:
        live_response = client.get("/api/v1/health/live")
        ready_response = client.get("/api/v1/health/ready")

    assert live_response.status_code == 200
    assert ready_response.status_code in {200, 503}

from __future__ import annotations

import time
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from redis import Redis
from redis.exceptions import (
    BusyLoadingError,
)
from redis.exceptions import (
    ConnectionError as RedisConnectionError,
)
from redis.exceptions import (
    TimeoutError as RedisTimeoutError,
)
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from testcontainers.core.container import DockerContainer
from testcontainers.postgres import PostgresContainer

from app.core.auth import AuthenticatedPrincipal, get_authenticated_principal
from app.core.config.settings import Settings
from app.core.db import dispose_engine
from app.core.redis import close_redis
from app.main import create_app
from tests.helpers.alembic import upgrade_database_to_head
from tests.helpers.asyncio_runner import run_async
from tests.helpers.auth import AuthenticatedClientBundle, FakeAuthProvider
from tests.helpers.settings import reset_settings_cache


@pytest.fixture(autouse=True)
def reset_runtime_state(monkeypatch, tmp_path):
    monkeypatch.setitem(Settings.model_config, "env_file", str(tmp_path / ".env.test"))
    monkeypatch.setenv("RATE_LIMITING__ENABLED", "false")

    reset_settings_cache()
    yield
    run_async(close_redis())
    run_async(dispose_engine())
    reset_settings_cache()


@pytest.fixture
def client_factory(monkeypatch):
    def _build(
        *,
        database_url: str | None = None,
        redis_url: str | None = None,
        rate_limiting_enabled: bool = False,
    ) -> TestClient:
        if database_url is None:
            monkeypatch.delenv("DATABASE__URL", raising=False)
        else:
            monkeypatch.setenv("DATABASE__URL", database_url)

        if redis_url is None:
            monkeypatch.delenv("REDIS__URL", raising=False)
        else:
            monkeypatch.setenv("REDIS__URL", redis_url)
        monkeypatch.setenv(
            "RATE_LIMITING__ENABLED",
            "true" if rate_limiting_enabled else "false",
        )

        reset_settings_cache()
        app = create_app()
        return TestClient(app)

    return _build


@pytest.fixture
def authenticated_client_factory(monkeypatch):
    def _build(
        *,
        identity: AuthenticatedPrincipal,
        database_url: str | None = None,
        redis_url: str | None = None,
        rate_limiting_enabled: bool = False,
    ) -> AuthenticatedClientBundle:
        if database_url is None:
            monkeypatch.delenv("DATABASE__URL", raising=False)
        else:
            monkeypatch.setenv("DATABASE__URL", database_url)

        if redis_url is None:
            monkeypatch.delenv("REDIS__URL", raising=False)
        else:
            monkeypatch.setenv("REDIS__URL", redis_url)
        monkeypatch.setenv(
            "RATE_LIMITING__ENABLED",
            "true" if rate_limiting_enabled else "false",
        )

        reset_settings_cache()
        test_auth_provider = FakeAuthProvider()
        test_auth_provider.set_identity(identity)
        app = create_app()
        app.dependency_overrides[get_authenticated_principal] = (
            test_auth_provider.get_authenticated_principal
        )
        return AuthenticatedClientBundle(
            client=TestClient(app),
            auth_provider=test_auth_provider,
        )

    return _build


@pytest.fixture
def client(client_factory) -> TestClient:
    with client_factory(database_url=None, redis_url=None) as test_client:
        yield test_client


@pytest.fixture
def migrated_database_url(tmp_path) -> str:
    database_url = f"sqlite+aiosqlite:///{tmp_path}/migrated.db"
    upgrade_database_to_head(database_url)
    return database_url


@pytest.fixture
def migrated_session_factory(migrated_database_url: str):
    engine = create_async_engine(migrated_database_url)
    session_factory = async_sessionmaker(
        engine,
        expire_on_commit=False,
        class_=AsyncSession,
    )
    yield session_factory
    run_async(engine.dispose())


@pytest.fixture(scope="session")
def postgres_integration_url() -> Iterator[str]:
    """
    Start an ephemeral PostgreSQL instance for integration tests.
    """
    with PostgresContainer("postgres:17-alpine", driver="psycopg") as postgres:
        yield postgres.get_connection_url()


@pytest.fixture(scope="session")
def redis_integration_url() -> Iterator[str]:
    """
    Start an ephemeral Redis instance for integration tests.
    """
    with DockerContainer("redis:7-alpine").with_exposed_ports(6379) as redis_container:
        host = redis_container.get_container_host_ip()
        port = redis_container.get_exposed_port(6379)
        redis_url = f"redis://{host}:{port}/0"

        client = Redis.from_url(redis_url)
        deadline = time.monotonic() + 30

        try:
            while True:
                try:
                    client.ping()
                    break
                except (RedisConnectionError, RedisTimeoutError, BusyLoadingError):
                    if time.monotonic() >= deadline:
                        raise
                    time.sleep(0.2)

            yield redis_url
        finally:
            client.close()

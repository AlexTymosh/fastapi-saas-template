from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.auth import AuthenticatedPrincipal, extract_authenticated_principal
from app.core.config.settings import Settings, get_settings
from app.core.db import dispose_engine
from app.main import create_app
from tests.helpers.alembic import upgrade_database_to_head
from tests.helpers.asyncio_runner import run_async
from tests.helpers.auth import TestAuthProvider


@pytest.fixture(autouse=True)
def reset_runtime_state(monkeypatch, tmp_path):
    monkeypatch.setitem(Settings.model_config, "env_file", str(tmp_path / ".env.test"))

    get_settings.cache_clear()
    yield
    run_async(dispose_engine())
    get_settings.cache_clear()


@pytest.fixture
def client_factory(monkeypatch):
    def _build(
        *,
        database_url: str | None = None,
        redis_url: str | None = None,
    ) -> TestClient:
        if database_url is None:
            monkeypatch.delenv("DATABASE__URL", raising=False)
        else:
            monkeypatch.setenv("DATABASE__URL", database_url)

        if redis_url is None:
            monkeypatch.delenv("REDIS__URL", raising=False)
        else:
            monkeypatch.setenv("REDIS__URL", redis_url)

        get_settings.cache_clear()
        app = create_app()
        return TestClient(app)

    return _build


@pytest.fixture
def test_auth_provider() -> TestAuthProvider:
    return TestAuthProvider()


@pytest.fixture
def authenticated_client_factory(monkeypatch, test_auth_provider: TestAuthProvider):
    def _build(
        *,
        identity: AuthenticatedPrincipal,
        database_url: str | None = None,
        redis_url: str | None = None,
    ) -> tuple[TestClient, TestAuthProvider]:
        if database_url is None:
            monkeypatch.delenv("DATABASE__URL", raising=False)
        else:
            monkeypatch.setenv("DATABASE__URL", database_url)

        if redis_url is None:
            monkeypatch.delenv("REDIS__URL", raising=False)
        else:
            monkeypatch.setenv("REDIS__URL", redis_url)

        get_settings.cache_clear()
        test_auth_provider.set_identity(identity)
        app = create_app()
        app.dependency_overrides[extract_authenticated_principal] = (
            test_auth_provider.extract_authenticated_principal
        )
        return TestClient(app), test_auth_provider

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

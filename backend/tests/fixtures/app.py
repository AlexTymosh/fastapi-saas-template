from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from tests.helpers.settings import reset_settings_cache


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
        if rate_limiting_enabled:
            monkeypatch.setenv(
                "RATE_LIMITING__IDENTIFIER_SECRET",
                "test-rate-limit-identifier-secret-32chars",
            )

        reset_settings_cache()
        app = create_app()
        return TestClient(app)

    return _build


@pytest.fixture
def client(client_factory) -> TestClient:
    with client_factory(database_url=None, redis_url=None) as test_client:
        yield test_client

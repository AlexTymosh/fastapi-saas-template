from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.core.auth import AuthenticatedPrincipal, get_authenticated_principal
from app.main import create_app
from tests.helpers.auth import AuthenticatedClientBundle, FakeAuthProvider
from tests.helpers.settings import reset_settings_cache


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
        if rate_limiting_enabled:
            monkeypatch.setenv(
                "RATE_LIMITING__IDENTIFIER_SECRET",
                "test-rate-limit-identifier-secret-32chars",
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

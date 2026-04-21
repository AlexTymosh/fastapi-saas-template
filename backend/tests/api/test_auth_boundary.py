from __future__ import annotations

from fastapi.testclient import TestClient

from app.core.auth import (
    AuthenticatedPrincipal,
    get_authenticated_principal,
    require_authenticated_principal,
)
from app.main import create_app


def _principal() -> AuthenticatedPrincipal:
    return AuthenticatedPrincipal(
        external_auth_id="kc-auth-boundary-user",
        email="boundary@example.com",
        email_verified=True,
        first_name="Boundary",
        last_name="User",
    )


def test_require_authenticated_principal_returns_401(client_factory) -> None:
    with client_factory(database_url=None, redis_url=None) as client:
        response = client.get("/api/v1/users/me")

    assert response.status_code == 401
    assert response.headers["content-type"].startswith("application/problem+json")


def test_authenticated_provider_override_resolves_principal(
    authenticated_client_factory,
    migrated_database_url: str,
) -> None:
    test_client, _ = authenticated_client_factory(
        identity=_principal(),
        database_url=migrated_database_url,
        redis_url=None,
    )
    with test_client as client:
        response = client.get("/api/v1/users/me")

    assert response.status_code == 200
    assert response.json()["external_auth_id"] == "kc-auth-boundary-user"


def test_endpoint_depends_on_auth_boundary_dependency(
    monkeypatch,
    migrated_database_url: str,
) -> None:
    monkeypatch.setenv("DATABASE__URL", migrated_database_url)
    monkeypatch.delenv("REDIS__URL", raising=False)

    app = create_app()

    async def _override_boundary() -> AuthenticatedPrincipal:
        return _principal()

    async def _override_provider(request=None):
        _ = request
        return None

    app.dependency_overrides[require_authenticated_principal] = _override_boundary
    app.dependency_overrides[get_authenticated_principal] = _override_provider

    with TestClient(app) as client:
        response = client.get("/api/v1/users/me")

    assert response.status_code == 200
    assert response.json()["external_auth_id"] == "kc-auth-boundary-user"

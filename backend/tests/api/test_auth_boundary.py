from __future__ import annotations

from fastapi.testclient import TestClient

from app.core.auth import (
    AuthenticatedPrincipal,
    get_authenticated_principal,
    get_keycloak_authenticator,
    require_authenticated_principal,
)
from app.core.config.settings import get_settings
from app.main import create_app
from tests.helpers.jwt import encode_rs256_jwt, generate_rsa_keypair, to_jwk


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


def test_protected_endpoint_accepts_valid_keycloak_like_bearer_token(
    monkeypatch,
    migrated_database_url: str,
) -> None:
    keypair = generate_rsa_keypair()
    kid = "integration-test-kid"
    jwk = to_jwk(keypair, kid=kid)

    issuer = "http://keycloak.test/realms/fastapi-dev"
    audience = "fastapi-backend"
    token = encode_rs256_jwt(
        keypair,
        kid=kid,
        claims={
            "sub": "kc-int-user-1",
            "iss": issuer,
            "aud": audience,
            "exp": 32503680000,
            "iat": 1700000000,
            "email": "integration@example.com",
            "email_verified": True,
            "given_name": "Integration",
            "family_name": "User",
            "realm_access": {"roles": ["member"]},
        },
    )

    monkeypatch.setenv("DATABASE__URL", migrated_database_url)
    monkeypatch.delenv("REDIS__URL", raising=False)
    monkeypatch.setenv("AUTH__ENABLED", "true")
    monkeypatch.setenv("AUTH__ISSUER_URL", issuer)
    monkeypatch.setenv("AUTH__AUDIENCE", audience)
    monkeypatch.setenv("AUTH__ALGORITHMS", "RS256")
    monkeypatch.delenv("AUTH__JWKS_URL", raising=False)

    get_settings.cache_clear()
    get_keycloak_authenticator.cache_clear()
    monkeypatch.setattr(
        "app.core.auth._fetch_json_document",
        lambda _url: {"keys": [jwk]},
    )

    with TestClient(create_app()) as client:
        response = client.get(
            "/api/v1/users/me",
            headers={"Authorization": f"Bearer {token}"},
        )

    assert response.status_code == 200
    assert response.json()["external_auth_id"] == "kc-int-user-1"

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.core.auth import (
    AuthenticatedPrincipal,
    KeycloakJwtAuthenticator,
    _extract_platform_roles,
    get_keycloak_authenticator,
)
from app.core.config.settings import get_settings
from app.core.errors.exceptions import UnauthorizedError
from tests.helpers.jwt import encode_rs256_jwt, generate_rsa_keypair, to_jwk

ISSUER = "http://keycloak.test/realms/fastapi-dev"
AUDIENCE = "fastapi-backend"
CLIENT_ID = "fastapi-backend"
KID = "test-kid-1"


@pytest.fixture(autouse=True)
def clear_authenticator_cache() -> None:
    get_keycloak_authenticator.cache_clear()
    yield
    get_keycloak_authenticator.cache_clear()


@pytest.fixture
def rsa_material() -> tuple[dict[str, object], object]:
    keypair = generate_rsa_keypair()
    return to_jwk(keypair, kid=KID), keypair


def _build_token(
    keypair,
    *,
    issuer: str = ISSUER,
    audience: str = AUDIENCE,
    expires_delta_seconds: int = 300,
    extra_claims: dict[str, object] | None = None,
) -> str:
    now = datetime.now(UTC)
    claims: dict[str, object] = {
        "sub": "kc-user-123",
        "iss": issuer,
        "aud": audience,
        "exp": int((now + timedelta(seconds=expires_delta_seconds)).timestamp()),
        "iat": int(now.timestamp()),
        "email": "claims@example.com",
        "email_verified": True,
        "given_name": "Given",
        "family_name": "Family",
    }
    if extra_claims:
        claims.update(extra_claims)

    return encode_rs256_jwt(keypair, kid=KID, claims=claims)


def _mock_auth_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AUTH__ENABLED", "true")
    monkeypatch.setenv("AUTH__ISSUER_URL", ISSUER)
    monkeypatch.setenv("AUTH__AUDIENCE", AUDIENCE)
    monkeypatch.setenv("AUTH__CLIENT_ID", CLIENT_ID)
    monkeypatch.setenv("AUTH__ALGORITHMS", "RS256")
    monkeypatch.delenv("AUTH__JWKS_URL", raising=False)
    get_settings.cache_clear()


def test_missing_authorization_header_returns_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _mock_auth_env(monkeypatch)

    principal = KeycloakJwtAuthenticator().authenticate(None)

    assert principal is None


def test_malformed_authorization_header_raises_unauthorized(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _mock_auth_env(monkeypatch)

    with pytest.raises(UnauthorizedError):
        KeycloakJwtAuthenticator().authenticate("Bearer")


def test_invalid_issuer_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
    rsa_material,
) -> None:
    _mock_auth_env(monkeypatch)
    jwk, keypair = rsa_material
    token = _build_token(keypair, issuer="http://wrong-issuer")

    monkeypatch.setattr(
        "app.core.auth._fetch_json_document",
        lambda _url: {"keys": [jwk]},
    )

    with pytest.raises(UnauthorizedError):
        KeycloakJwtAuthenticator().authenticate(f"Bearer {token}")


def test_invalid_audience_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
    rsa_material,
) -> None:
    _mock_auth_env(monkeypatch)
    jwk, keypair = rsa_material
    token = _build_token(keypair, audience="other-aud")

    monkeypatch.setattr(
        "app.core.auth._fetch_json_document",
        lambda _url: {"keys": [jwk]},
    )

    with pytest.raises(UnauthorizedError):
        KeycloakJwtAuthenticator().authenticate(f"Bearer {token}")


def test_expired_token_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
    rsa_material,
) -> None:
    _mock_auth_env(monkeypatch)
    jwk, keypair = rsa_material
    token = _build_token(keypair, expires_delta_seconds=-1)

    monkeypatch.setattr(
        "app.core.auth._fetch_json_document",
        lambda _url: {"keys": [jwk]},
    )

    with pytest.raises(UnauthorizedError):
        KeycloakJwtAuthenticator().authenticate(f"Bearer {token}")


def test_valid_claims_map_to_authenticated_principal(
    monkeypatch: pytest.MonkeyPatch,
    rsa_material,
) -> None:
    _mock_auth_env(monkeypatch)
    jwk, keypair = rsa_material
    token = _build_token(
        keypair,
        extra_claims={"realm_access": {"roles": ["member", "superadmin"]}},
    )

    monkeypatch.setattr(
        "app.core.auth._fetch_json_document",
        lambda _url: {"keys": [jwk]},
    )

    principal = KeycloakJwtAuthenticator().authenticate(f"Bearer {token}")

    assert principal == AuthenticatedPrincipal(
        external_auth_id="kc-user-123",
        email="claims@example.com",
        email_verified=True,
        first_name="Given",
        last_name="Family",
        platform_roles=["member", "superadmin"],
    )


def test_extract_roles_from_realm_access() -> None:
    roles = _extract_platform_roles(
        {
            "realm_access": {
                "roles": ["owner", "member"],
            }
        },
        client_id=CLIENT_ID,
    )

    assert roles == ["owner", "member"]


def test_extract_roles_from_resource_access_client() -> None:
    roles = _extract_platform_roles(
        {
            "resource_access": {
                CLIENT_ID: {
                    "roles": ["admin", "manager"],
                }
            }
        },
        client_id=CLIENT_ID,
    )

    assert roles == ["admin", "manager"]


def test_extract_roles_merges_realm_and_resource_access() -> None:
    roles = _extract_platform_roles(
        {
            "realm_access": {"roles": ["member", "superadmin"]},
            "resource_access": {CLIENT_ID: {"roles": ["member", "editor"]}},
        },
        client_id=CLIENT_ID,
    )

    assert roles == ["member", "superadmin", "editor"]

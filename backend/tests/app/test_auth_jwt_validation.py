from __future__ import annotations

from collections.abc import Callable

import pytest
from starlette.requests import Request

from app.core.auth import JwtValidator, get_authenticated_principal
from app.core.config.settings import AuthSettings
from app.core.errors.exceptions import UnauthorizedError
from tests.helpers.asyncio_runner import run_async
from tests.helpers.jwt import generate_rsa_jwk, issue_access_token

ISSUER = "http://localhost:8080/realms/fastapi-saas"
JWKS_URL = "http://mock-idp/jwks"
DISCOVERY_URL = f"{ISSUER}/.well-known/openid-configuration"


def _request_with_headers(headers: dict[str, str]) -> Request:
    scope = {
        "type": "http",
        "method": "GET",
        "path": "/api/v1/users/me",
        "headers": [
            (key.lower().encode("utf-8"), value.encode("utf-8"))
            for key, value in headers.items()
        ],
    }
    return Request(scope)


def _make_fetcher(jwks: dict[str, object]) -> Callable[[str], dict[str, object]]:
    def _fetch(url: str) -> dict[str, object]:
        if url == DISCOVERY_URL:
            return {"jwks_uri": JWKS_URL}
        if url == JWKS_URL:
            return jwks
        raise AssertionError(f"Unexpected URL requested: {url}")

    return _fetch


def _build_validator(fetcher: Callable[[str], dict[str, object]]) -> JwtValidator:
    return JwtValidator(
        auth_settings=AuthSettings(
            enabled=True,
            issuer_url=ISSUER,
            audience="fastapi-backend",
            algorithms=["RS256"],
            leeway_seconds=0,
        ),
        fetch_json=fetcher,
    )


def test_missing_authorization_header_returns_none() -> None:
    request = _request_with_headers({})

    result = run_async(get_authenticated_principal(request))

    assert result is None


def test_malformed_authorization_header_raises_unauthorized() -> None:
    request = _request_with_headers({"Authorization": "invalid-header"})

    with pytest.raises(UnauthorizedError, match="Malformed Authorization"):
        run_async(get_authenticated_principal(request))


def test_invalid_issuer_is_rejected() -> None:
    jwk, private_key = generate_rsa_jwk()
    token = issue_access_token(
        private_key=private_key,
        kid=jwk["kid"],
        issuer="http://localhost:8080/realms/other",
        audience="fastapi-backend",
        subject="kc-sub-issuer",
    )
    validator = _build_validator(_make_fetcher({"keys": [jwk]}))

    with pytest.raises(UnauthorizedError, match="Invalid token issuer"):
        run_async(validator.validate_token(token))


def test_invalid_audience_is_rejected() -> None:
    jwk, private_key = generate_rsa_jwk()
    token = issue_access_token(
        private_key=private_key,
        kid=jwk["kid"],
        issuer=ISSUER,
        audience="other-audience",
        subject="kc-sub-aud",
    )
    validator = _build_validator(_make_fetcher({"keys": [jwk]}))

    with pytest.raises(UnauthorizedError, match="Invalid token audience"):
        run_async(validator.validate_token(token))


def test_expired_token_is_rejected() -> None:
    jwk, private_key = generate_rsa_jwk()
    token = issue_access_token(
        private_key=private_key,
        kid=jwk["kid"],
        issuer=ISSUER,
        audience="fastapi-backend",
        subject="kc-sub-expired",
        expires_in_seconds=-30,
    )
    validator = _build_validator(_make_fetcher({"keys": [jwk]}))

    with pytest.raises(UnauthorizedError, match="Token has expired"):
        run_async(validator.validate_token(token))


def test_valid_keycloak_like_claims_map_to_authenticated_principal() -> None:
    jwk, private_key = generate_rsa_jwk()
    token = issue_access_token(
        private_key=private_key,
        kid=jwk["kid"],
        issuer=ISSUER,
        audience="fastapi-backend",
        subject="kc-sub-claims",
        claims={
            "email": "claim-user@example.com",
            "email_verified": True,
            "given_name": "Claim",
            "family_name": "User",
            "realm_access": {"roles": ["member"]},
            "resource_access": {
                "fastapi-backend": {
                    "roles": ["org-admin"],
                }
            },
        },
    )
    validator = _build_validator(_make_fetcher({"keys": [jwk]}))

    claims = run_async(validator.validate_token(token))

    from app.core.auth import AuthenticatedPrincipal

    principal = AuthenticatedPrincipal.from_verified_jwt_claims(
        claims,
        resource_client_id="fastapi-backend",
    )

    assert principal.external_auth_id == "kc-sub-claims"
    assert principal.email == "claim-user@example.com"
    assert principal.email_verified is True
    assert principal.first_name == "Claim"
    assert principal.last_name == "User"
    assert principal.platform_roles == ["member", "org-admin"]


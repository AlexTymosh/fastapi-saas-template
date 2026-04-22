from __future__ import annotations

from collections.abc import Callable

import jwt
import pytest
from starlette.requests import Request

import app.core.auth_jwt as auth_jwt_module
from app.core.auth import get_authenticated_principal
from app.core.auth_jwt import JwtValidator
from app.core.config.settings import AuthSettings, get_settings
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


def test_token_with_disallowed_signing_algorithm_is_rejected() -> None:
    token = jwt.encode(
        {
            "iss": ISSUER,
            "aud": "fastapi-backend",
            "sub": "kc-sub-hs256",
            "exp": 4_200_000_000,
        },
        key="dev-secret",
        algorithm="HS256",
        headers={"kid": "ignored"},
    )
    validator = _build_validator(_make_fetcher({"keys": []}))

    with pytest.raises(
        UnauthorizedError,
        match="Token signing algorithm is not allowed",
    ):
        run_async(validator.validate_token(token))


def test_jwks_kid_miss_refreshes_once_and_succeeds() -> None:
    jwk, private_key = generate_rsa_jwk()
    token = issue_access_token(
        private_key=private_key,
        kid=jwk["kid"],
        issuer=ISSUER,
        audience="fastapi-backend",
        subject="kc-sub-refresh-success",
    )
    calls = {"jwks": 0}

    def _fetch(url: str) -> dict[str, object]:
        if url == DISCOVERY_URL:
            return {"jwks_uri": JWKS_URL}
        if url == JWKS_URL:
            calls["jwks"] += 1
            if calls["jwks"] == 1:
                return {"keys": []}
            return {"keys": [jwk]}
        raise AssertionError(f"Unexpected URL requested: {url}")

    validator = _build_validator(_fetch)

    claims = run_async(validator.validate_token(token))

    assert claims["sub"] == "kc-sub-refresh-success"
    assert calls["jwks"] == 2


def test_jwks_kid_miss_after_refresh_still_fails() -> None:
    jwk, private_key = generate_rsa_jwk()
    token = issue_access_token(
        private_key=private_key,
        kid=jwk["kid"],
        issuer=ISSUER,
        audience="fastapi-backend",
        subject="kc-sub-refresh-fail",
    )
    other_jwk, _ = generate_rsa_jwk()
    calls = {"jwks": 0}

    def _fetch(url: str) -> dict[str, object]:
        if url == DISCOVERY_URL:
            return {"jwks_uri": JWKS_URL}
        if url == JWKS_URL:
            calls["jwks"] += 1
            return {"keys": [other_jwk]}
        raise AssertionError(f"Unexpected URL requested: {url}")

    validator = _build_validator(_fetch)

    with pytest.raises(UnauthorizedError, match="Unable to match token signing key"):
        run_async(validator.validate_token(token))

    assert calls["jwks"] == 2


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
                "fastapi-web": {
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
        resource_client_id="fastapi-web",
    )

    assert principal.external_auth_id == "kc-sub-claims"
    assert principal.email == "claim-user@example.com"
    assert principal.email_verified is True
    assert principal.first_name == "Claim"
    assert principal.last_name == "User"
    assert principal.platform_roles == ["member", "org-admin"]


def test_authenticated_principal_uses_auth_client_id_for_resource_roles(
    monkeypatch,
) -> None:
    jwk, private_key = generate_rsa_jwk()

    def _fetch(url: str) -> dict[str, object]:
        if url == DISCOVERY_URL:
            return {"jwks_uri": JWKS_URL}
        if url == JWKS_URL:
            return {"keys": [jwk]}
        raise AssertionError(f"Unexpected URL requested: {url}")

    monkeypatch.setenv("AUTH__ENABLED", "true")
    monkeypatch.setenv("AUTH__ISSUER_URL", ISSUER)
    monkeypatch.setenv("AUTH__AUDIENCE", "fastapi-backend")
    monkeypatch.setenv("AUTH__CLIENT_ID", "fastapi-web")
    monkeypatch.setattr(auth_jwt_module, "_fetch_json_url", _fetch)
    monkeypatch.setattr(auth_jwt_module, "_jwt_validator", None)
    monkeypatch.setattr(auth_jwt_module, "_jwt_validator_signature", None)
    get_settings.cache_clear()

    token = issue_access_token(
        private_key=private_key,
        kid=jwk["kid"],
        issuer=ISSUER,
        audience="fastapi-backend",
        subject="kc-client-role-user",
        claims={
            "resource_access": {
                "fastapi-web": {
                    "roles": ["org-admin"],
                }
            },
        },
    )
    request = _request_with_headers({"Authorization": f"Bearer {token}"})
    principal = run_async(get_authenticated_principal(request))

    assert principal is not None
    assert principal.platform_roles == ["org-admin"]

    get_settings.cache_clear()

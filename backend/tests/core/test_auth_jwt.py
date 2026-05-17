from __future__ import annotations

import asyncio
from collections.abc import Callable

import jwt
import pytest
from starlette.requests import Request

import app.core.auth_jwt as auth_jwt_module
from app.core.auth import JwtValidator, get_authenticated_principal
from app.core.config.settings import AuthSettings
from app.core.errors.exceptions import UnauthorizedError
from tests.helpers.asyncio_runner import run_async
from tests.helpers.jwt import generate_rsa_jwk, issue_access_token
from tests.helpers.settings import reset_settings_cache

pytestmark = [pytest.mark.security, pytest.mark.auth]

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
            audience="fastapi-api",
            algorithms="RS256",
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


def test_validator_rejects_when_auth_disabled() -> None:
    validator = JwtValidator(
        auth_settings=AuthSettings(enabled=False),
        fetch_json=lambda url: {"keys": []},
    )

    with pytest.raises(UnauthorizedError) as exc_info:
        run_async(validator.validate_token("not-a-token"))

    assert exc_info.value.detail == "Invalid bearer token"


def test_invalid_issuer_is_rejected() -> None:
    jwk, private_key = generate_rsa_jwk()
    token = issue_access_token(
        private_key=private_key,
        kid=jwk["kid"],
        issuer="http://localhost:8080/realms/other",
        audience="fastapi-api",
        subject="kc-sub-issuer",
    )
    validator = _build_validator(_make_fetcher({"keys": [jwk]}))

    with pytest.raises(UnauthorizedError, match="Invalid bearer token"):
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

    with pytest.raises(UnauthorizedError, match="Invalid bearer token"):
        run_async(validator.validate_token(token))


def test_expired_token_is_rejected() -> None:
    jwk, private_key = generate_rsa_jwk()
    token = issue_access_token(
        private_key=private_key,
        kid=jwk["kid"],
        issuer=ISSUER,
        audience="fastapi-api",
        subject="kc-sub-expired",
        expires_in_seconds=-30,
    )
    validator = _build_validator(_make_fetcher({"keys": [jwk]}))

    with pytest.raises(UnauthorizedError, match="Invalid bearer token"):
        run_async(validator.validate_token(token))


def test_token_with_disallowed_signing_algorithm_is_rejected() -> None:
    token = jwt.encode(
        {
            "iss": ISSUER,
            "aud": "fastapi-api",
            "sub": "kc-sub-hs256",
            "exp": 4_200_000_000,
        },
        key="dev-secret-dev-secret-dev-secret-32b",
        algorithm="HS256",
        headers={"kid": "ignored"},
    )
    validator = _build_validator(_make_fetcher({"keys": []}))

    with pytest.raises(UnauthorizedError, match="Invalid bearer token"):
        run_async(validator.validate_token(token))


def test_valid_keycloak_like_claims_map_to_authenticated_principal() -> None:
    jwk, private_key = generate_rsa_jwk()
    token = issue_access_token(
        private_key=private_key,
        kid=jwk["kid"],
        issuer=ISSUER,
        audience="fastapi-api",
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
    assert principal.external_auth_id == "kc-sub-claims"
    assert not hasattr(principal, "platform_roles")


def test_valid_token_uses_api_audience_and_web_client_roles_split() -> None:
    jwk, private_key = generate_rsa_jwk()
    token = issue_access_token(
        private_key=private_key,
        kid=jwk["kid"],
        issuer=ISSUER,
        audience="fastapi-api",
        subject="kc-split-contract-user",
        claims={
            "resource_access": {
                "fastapi-web": {
                    "roles": ["viewer"],
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

    assert claims["aud"] == "fastapi-api"
    assert principal.external_auth_id == "kc-split-contract-user"
    assert not hasattr(principal, "platform_roles")


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
    monkeypatch.setenv("AUTH__AUDIENCE", "fastapi-api")
    monkeypatch.setenv("AUTH__CLIENT_ID", "fastapi-web")
    monkeypatch.setattr(auth_jwt_module, "_fetch_json_url", _fetch)
    monkeypatch.setattr(auth_jwt_module, "_jwt_validator", None)
    monkeypatch.setattr(auth_jwt_module, "_jwt_validator_signature", None)
    reset_settings_cache()

    token = issue_access_token(
        private_key=private_key,
        kid=jwk["kid"],
        issuer=ISSUER,
        audience="fastapi-api",
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
    assert principal.external_auth_id == "kc-client-role-user"
    assert not hasattr(principal, "platform_roles")

    reset_settings_cache()


def test_jwt_validation_retries_once_after_kid_miss_and_succeeds() -> None:
    stale_jwk, _ = generate_rsa_jwk(kid="stale-kid")
    fresh_jwk, fresh_private_key = generate_rsa_jwk(kid="fresh-kid")
    token = issue_access_token(
        private_key=fresh_private_key,
        kid=fresh_jwk["kid"],
        issuer=ISSUER,
        audience="fastapi-api",
        subject="kc-sub-rotated",
    )
    fetch_count = 0

    def _fetch(url: str) -> dict[str, object]:
        nonlocal fetch_count
        if url == DISCOVERY_URL:
            return {"jwks_uri": JWKS_URL}
        if url == JWKS_URL:
            fetch_count += 1
            if fetch_count == 1:
                return {"keys": [stale_jwk]}
            return {"keys": [fresh_jwk]}
        raise AssertionError(f"Unexpected URL requested: {url}")

    validator = _build_validator(_fetch)

    claims = run_async(validator.validate_token(token))

    assert claims["sub"] == "kc-sub-rotated"
    assert fetch_count == 2


def test_jwt_validation_fails_if_refreshed_jwks_still_misses_kid() -> None:
    stale_jwk, _ = generate_rsa_jwk(kid="stale-kid")
    token_jwk, token_private_key = generate_rsa_jwk(kid="token-kid")
    token = issue_access_token(
        private_key=token_private_key,
        kid=token_jwk["kid"],
        issuer=ISSUER,
        audience="fastapi-api",
        subject="kc-sub-unknown-kid",
    )
    fetch_count = 0

    def _fetch(url: str) -> dict[str, object]:
        nonlocal fetch_count
        if url == DISCOVERY_URL:
            return {"jwks_uri": JWKS_URL}
        if url == JWKS_URL:
            fetch_count += 1
            return {"keys": [stale_jwk]}
        raise AssertionError(f"Unexpected URL requested: {url}")

    validator = _build_validator(_fetch)

    with pytest.raises(UnauthorizedError, match="Invalid bearer token"):
        run_async(validator.validate_token(token))

    assert fetch_count == 2


def _build_strict_validator(
    fetcher: Callable[[str], dict[str, object]],
    *,
    allowed_authorized_parties: list[str] | None = None,
    max_token_lifetime_seconds: int = 3600,
    jwks_refresh_cooldown_seconds: float = 30.0,
) -> JwtValidator:
    return JwtValidator(
        auth_settings=AuthSettings(
            enabled=True,
            issuer_url=ISSUER,
            audience="fastapi-api",
            allowed_authorized_parties=allowed_authorized_parties or [],
            algorithms="RS256",
            leeway_seconds=0,
            max_token_lifetime_seconds=max_token_lifetime_seconds,
            jwks_refresh_cooldown_seconds=jwks_refresh_cooldown_seconds,
            jwks_refresh_lock_timeout_seconds=0.1,
        ),
        fetch_json=fetcher,
    )


def test_missing_audience_is_rejected_when_audience_configured() -> None:
    jwk, private_key = generate_rsa_jwk()
    token = issue_access_token(
        private_key=private_key,
        kid=jwk["kid"],
        issuer=ISSUER,
        audience="fastapi-api",
        subject="kc-sub-no-aud",
        claims={"aud": None},
    )
    validator = _build_strict_validator(_make_fetcher({"keys": [jwk]}))

    with pytest.raises(UnauthorizedError, match="Invalid bearer token"):
        run_async(validator.validate_token(token))


def test_correct_audience_is_accepted() -> None:
    jwk, private_key = generate_rsa_jwk()
    token = issue_access_token(
        private_key=private_key,
        kid=jwk["kid"],
        issuer=ISSUER,
        audience="fastapi-api",
        subject="kc-sub-correct-aud",
    )
    validator = _build_strict_validator(_make_fetcher({"keys": [jwk]}))

    claims = run_async(validator.validate_token(token))

    assert claims["sub"] == "kc-sub-correct-aud"


def test_missing_iat_is_rejected_when_required() -> None:
    jwk, private_key = generate_rsa_jwk()
    token = issue_access_token(
        private_key=private_key,
        kid=jwk["kid"],
        issuer=ISSUER,
        audience="fastapi-api",
        subject="kc-sub-no-iat",
        claims={"iat": None},
    )
    validator = _build_strict_validator(_make_fetcher({"keys": [jwk]}))

    with pytest.raises(UnauthorizedError, match="Invalid bearer token"):
        run_async(validator.validate_token(token))


def test_malformed_iat_is_rejected() -> None:
    jwk, private_key = generate_rsa_jwk()
    token = issue_access_token(
        private_key=private_key,
        kid=jwk["kid"],
        issuer=ISSUER,
        audience="fastapi-api",
        subject="kc-sub-bad-iat",
        claims={"iat": "not-a-timestamp"},
    )
    validator = _build_strict_validator(_make_fetcher({"keys": [jwk]}))

    with pytest.raises(UnauthorizedError, match="Invalid bearer token"):
        run_async(validator.validate_token(token))


def test_excessive_token_lifetime_is_rejected() -> None:
    jwk, private_key = generate_rsa_jwk()
    token = issue_access_token(
        private_key=private_key,
        kid=jwk["kid"],
        issuer=ISSUER,
        audience="fastapi-api",
        subject="kc-sub-long-lived",
        expires_in_seconds=7200,
    )
    validator = _build_strict_validator(
        _make_fetcher({"keys": [jwk]}),
        max_token_lifetime_seconds=300,
    )

    with pytest.raises(UnauthorizedError, match="Invalid bearer token"):
        run_async(validator.validate_token(token))


def test_missing_kid_is_rejected_when_required() -> None:
    jwk, private_key = generate_rsa_jwk()
    token = jwt.encode(
        {
            "iss": ISSUER,
            "aud": "fastapi-api",
            "sub": "kc-sub-no-kid",
            "iat": 4_000_000_000,
            "exp": 4_000_000_300,
        },
        key=private_key,
        algorithm="RS256",
        headers={},
    )
    validator = _build_strict_validator(_make_fetcher({"keys": [jwk]}))

    with pytest.raises(UnauthorizedError, match="Invalid bearer token"):
        run_async(validator.validate_token(token))


def test_wrong_azp_is_rejected_with_generic_detail() -> None:
    jwk, private_key = generate_rsa_jwk()
    token = issue_access_token(
        private_key=private_key,
        kid=jwk["kid"],
        issuer=ISSUER,
        audience="fastapi-api",
        subject="kc-sub-wrong-azp",
        claims={"azp": "untrusted-client"},
    )
    validator = _build_strict_validator(
        _make_fetcher({"keys": [jwk]}),
        allowed_authorized_parties=["fastapi-web"],
    )

    with pytest.raises(UnauthorizedError) as exc_info:
        run_async(validator.validate_token(token))

    assert exc_info.value.detail == "Invalid bearer token"


def test_allowed_azp_is_accepted() -> None:
    jwk, private_key = generate_rsa_jwk()
    token = issue_access_token(
        private_key=private_key,
        kid=jwk["kid"],
        issuer=ISSUER,
        audience="fastapi-api",
        subject="kc-sub-good-azp",
        claims={"azp": "fastapi-web"},
    )
    validator = _build_strict_validator(
        _make_fetcher({"keys": [jwk]}),
        allowed_authorized_parties=["fastapi-web"],
    )

    claims = run_async(validator.validate_token(token))

    assert claims["azp"] == "fastapi-web"


def test_unknown_kid_forced_refresh_uses_cooldown() -> None:
    stale_jwk, _ = generate_rsa_jwk(kid="stale-kid")
    token_jwk, token_private_key = generate_rsa_jwk(kid="token-kid")
    token = issue_access_token(
        private_key=token_private_key,
        kid=token_jwk["kid"],
        issuer=ISSUER,
        audience="fastapi-api",
        subject="kc-sub-cooldown",
    )
    fetch_count = 0

    def _fetch(url: str) -> dict[str, object]:
        nonlocal fetch_count
        if url == DISCOVERY_URL:
            return {"jwks_uri": JWKS_URL}
        if url == JWKS_URL:
            fetch_count += 1
            return {"keys": [stale_jwk]}
        raise AssertionError(f"Unexpected URL requested: {url}")

    validator = _build_strict_validator(_fetch)

    for _ in range(3):
        with pytest.raises(UnauthorizedError):
            run_async(validator.validate_token(token))

    assert fetch_count == 2


def test_unknown_kid_concurrent_requests_share_single_forced_refresh() -> None:
    stale_jwk, _ = generate_rsa_jwk(kid="stale-kid")
    token_jwk, token_private_key = generate_rsa_jwk(kid="token-kid")
    token = issue_access_token(
        private_key=token_private_key,
        kid=token_jwk["kid"],
        issuer=ISSUER,
        audience="fastapi-api",
        subject="kc-sub-concurrent",
    )
    fetch_count = 0

    def _fetch(url: str) -> dict[str, object]:
        nonlocal fetch_count
        if url == DISCOVERY_URL:
            return {"jwks_uri": JWKS_URL}
        if url == JWKS_URL:
            fetch_count += 1
            return {"keys": [stale_jwk]}
        raise AssertionError(f"Unexpected URL requested: {url}")

    async def _run() -> None:
        validator = _build_strict_validator(_fetch)
        await validator._get_jwks()
        results = await asyncio.gather(
            *(validator.validate_token(token) for _ in range(5)),
            return_exceptions=True,
        )
        assert all(isinstance(result, UnauthorizedError) for result in results)

    run_async(_run())

    assert fetch_count == 2


def test_after_cooldown_new_key_can_be_loaded_by_forced_refresh() -> None:
    stale_jwk, _ = generate_rsa_jwk(kid="stale-kid")
    fresh_jwk, fresh_private_key = generate_rsa_jwk(kid="fresh-kid")
    token = issue_access_token(
        private_key=fresh_private_key,
        kid=fresh_jwk["kid"],
        issuer=ISSUER,
        audience="fastapi-api",
        subject="kc-sub-after-cooldown",
    )
    fetch_count = 0

    def _fetch(url: str) -> dict[str, object]:
        nonlocal fetch_count
        if url == DISCOVERY_URL:
            return {"jwks_uri": JWKS_URL}
        if url == JWKS_URL:
            fetch_count += 1
            if fetch_count < 3:
                return {"keys": [stale_jwk]}
            return {"keys": [fresh_jwk]}
        raise AssertionError(f"Unexpected URL requested: {url}")

    validator = _build_strict_validator(
        _fetch,
        jwks_refresh_cooldown_seconds=0.01,
    )
    with pytest.raises(UnauthorizedError):
        run_async(validator.validate_token(token))

    run_async(asyncio.sleep(0.02))
    claims = run_async(validator.validate_token(token))

    assert claims["sub"] == "kc-sub-after-cooldown"
    assert fetch_count == 3


def test_failed_forced_refresh_preserves_existing_jwks_cache() -> None:
    known_jwk, known_private_key = generate_rsa_jwk(kid="known-kid")
    unknown_jwk, unknown_private_key = generate_rsa_jwk(kid="unknown-kid")
    known_token = issue_access_token(
        private_key=known_private_key,
        kid=known_jwk["kid"],
        issuer=ISSUER,
        audience="fastapi-api",
        subject="kc-sub-known",
    )
    unknown_token = issue_access_token(
        private_key=unknown_private_key,
        kid=unknown_jwk["kid"],
        issuer=ISSUER,
        audience="fastapi-api",
        subject="kc-sub-unknown",
    )
    fetch_count = 0

    def _fetch(url: str) -> dict[str, object]:
        nonlocal fetch_count
        if url == DISCOVERY_URL:
            return {"jwks_uri": JWKS_URL}
        if url == JWKS_URL:
            fetch_count += 1
            if fetch_count == 1:
                return {"keys": [known_jwk]}
            raise UnauthorizedError(detail="Unable to fetch identity metadata")
        raise AssertionError(f"Unexpected URL requested: {url}")

    validator = _build_strict_validator(_fetch)

    assert run_async(validator.validate_token(known_token))["sub"] == "kc-sub-known"
    with pytest.raises(UnauthorizedError):
        run_async(validator.validate_token(unknown_token))
    assert run_async(validator.validate_token(known_token))["sub"] == "kc-sub-known"
    assert fetch_count == 2

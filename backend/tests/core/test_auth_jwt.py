from __future__ import annotations

import asyncio
import time
from collections.abc import Callable
from threading import Lock

import jwt
import pytest

from app.core.auth import JwtValidator
from app.core.config.settings import AuthSettings
from app.core.errors.exceptions import UnauthorizedError
from tests.helpers.asyncio_runner import run_async
from tests.helpers.jwt import generate_rsa_jwk, issue_access_token

pytestmark = [pytest.mark.security, pytest.mark.auth]

ISSUER = "http://localhost:8080/realms/fastapi-saas"
JWKS_URL = "http://mock-idp/jwks"
DISCOVERY_URL = f"{ISSUER}/.well-known/openid-configuration"


def _settings(**overrides: object) -> AuthSettings:
    values = {
        "enabled": True,
        "issuer_url": ISSUER,
        "audience": "fastapi-api",
        "algorithms": "RS256",
        "leeway_seconds": 0,
        "allowed_authorized_parties": ["fastapi-web"],
        "jwks_refresh_cooldown_seconds": 30.0,
        "jwks_refresh_lock_timeout_seconds": 1.0,
    }
    values.update(overrides)
    return AuthSettings(**values)


def _fetcher(jwks: dict[str, object]) -> Callable[[str], dict[str, object]]:
    def _fetch(url: str) -> dict[str, object]:
        if url == DISCOVERY_URL:
            return {"issuer": ISSUER, "jwks_uri": JWKS_URL}
        if url == JWKS_URL:
            return jwks
        raise AssertionError(f"Unexpected URL requested: {url}")

    return _fetch


def _validator(
    jwks: dict[str, object],
    **settings_overrides: object,
) -> JwtValidator:
    return JwtValidator(
        auth_settings=_settings(**settings_overrides),
        fetch_json=_fetcher(jwks),
    )


def _assert_invalid(token: str, validator: JwtValidator) -> None:
    with pytest.raises(UnauthorizedError) as exc_info:
        run_async(validator.validate_token(token))
    assert exc_info.value.detail == "Invalid bearer token"


def test_rejects_token_with_missing_aud_when_audience_is_configured() -> None:
    jwk, private_key = generate_rsa_jwk()
    token = issue_access_token(
        private_key=private_key,
        kid=jwk["kid"],
        issuer=ISSUER,
        audience=None,
        subject="kc-sub-missing-aud",
        claims={"azp": "fastapi-web"},
    )

    _assert_invalid(token, _validator({"keys": [jwk]}))


def test_rejects_wrong_aud() -> None:
    jwk, private_key = generate_rsa_jwk()
    token = issue_access_token(
        private_key=private_key,
        kid=jwk["kid"],
        issuer=ISSUER,
        audience="other-api",
        subject="kc-sub-wrong-aud",
        claims={"azp": "fastapi-web"},
    )

    _assert_invalid(token, _validator({"keys": [jwk]}))


def test_accepts_correct_aud_and_authorized_party() -> None:
    jwk, private_key = generate_rsa_jwk()
    token = issue_access_token(
        private_key=private_key,
        kid=jwk["kid"],
        issuer=ISSUER,
        audience="fastapi-api",
        subject="kc-sub-valid",
        claims={"azp": "fastapi-web"},
    )

    claims = run_async(_validator({"keys": [jwk]}).validate_token(token))

    assert claims["sub"] == "kc-sub-valid"


def test_rejects_missing_iat_when_required() -> None:
    jwk, private_key = generate_rsa_jwk()
    token = issue_access_token(
        private_key=private_key,
        kid=jwk["kid"],
        issuer=ISSUER,
        audience="fastapi-api",
        subject="kc-sub-no-iat",
        claims={"azp": "fastapi-web", "iat": None},
    )

    _assert_invalid(token, _validator({"keys": [jwk]}))


def test_rejects_malformed_iat_when_required() -> None:
    jwk, private_key = generate_rsa_jwk()
    token = issue_access_token(
        private_key=private_key,
        kid=jwk["kid"],
        issuer=ISSUER,
        audience="fastapi-api",
        subject="kc-sub-bad-iat",
        claims={"azp": "fastapi-web", "iat": "not-a-timestamp"},
    )

    _assert_invalid(token, _validator({"keys": [jwk]}))


def test_rejects_token_lifetime_greater_than_configured_maximum() -> None:
    jwk, private_key = generate_rsa_jwk()
    token = issue_access_token(
        private_key=private_key,
        kid=jwk["kid"],
        issuer=ISSUER,
        audience="fastapi-api",
        subject="kc-sub-long-lived",
        claims={"azp": "fastapi-web"},
        expires_in_seconds=7200,
    )

    _assert_invalid(token, _validator({"keys": [jwk]}, max_token_lifetime_seconds=3600))


def test_rejects_missing_kid_when_required() -> None:
    jwk, private_key = generate_rsa_jwk()
    token = issue_access_token(
        private_key=private_key,
        kid=None,
        issuer=ISSUER,
        audience="fastapi-api",
        subject="kc-sub-no-kid",
        claims={"azp": "fastapi-web"},
    )

    _assert_invalid(token, _validator({"keys": [jwk]}))


def test_rejects_wrong_azp() -> None:
    jwk, private_key = generate_rsa_jwk()
    token = issue_access_token(
        private_key=private_key,
        kid=jwk["kid"],
        issuer=ISSUER,
        audience="fastapi-api",
        subject="kc-sub-wrong-azp",
        claims={"azp": "untrusted-client"},
    )

    _assert_invalid(token, _validator({"keys": [jwk]}))


def test_rejects_unsupported_alg_with_generic_error() -> None:
    token = jwt.encode(
        {
            "iss": ISSUER,
            "aud": "fastapi-api",
            "sub": "kc-sub-hs256",
            "iat": int(time.time()),
            "exp": int(time.time()) + 300,
            "azp": "fastapi-web",
        },
        key="dev-secret-dev-secret-dev-secret-32b",
        algorithm="HS256",
        headers={"kid": "ignored"},
    )

    _assert_invalid(token, _validator({"keys": []}))


def test_unknown_kid_triggers_at_most_one_forced_refresh_within_cooldown() -> None:
    stale_jwk, _ = generate_rsa_jwk(kid="stale-kid")
    token_jwk, token_private_key = generate_rsa_jwk(kid="unknown-kid")
    token = issue_access_token(
        private_key=token_private_key,
        kid=token_jwk["kid"],
        issuer=ISSUER,
        audience="fastapi-api",
        subject="kc-sub-unknown-kid",
        claims={"azp": "fastapi-web"},
    )
    jwks_fetches = 0

    def _fetch(url: str) -> dict[str, object]:
        nonlocal jwks_fetches
        if url == DISCOVERY_URL:
            return {"jwks_uri": JWKS_URL}
        if url == JWKS_URL:
            jwks_fetches += 1
            return {"keys": [stale_jwk]}
        raise AssertionError(f"Unexpected URL requested: {url}")

    validator = JwtValidator(auth_settings=_settings(), fetch_json=_fetch)

    for _ in range(3):
        _assert_invalid(token, validator)

    assert jwks_fetches == 2


def test_concurrent_unknown_kid_requests_singleflight_forced_refresh() -> None:
    stale_jwk, _ = generate_rsa_jwk(kid="stale-kid")
    token_jwk, token_private_key = generate_rsa_jwk(kid="unknown-kid")
    token = issue_access_token(
        private_key=token_private_key,
        kid=token_jwk["kid"],
        issuer=ISSUER,
        audience="fastapi-api",
        subject="kc-sub-concurrent",
        claims={"azp": "fastapi-web"},
    )
    jwks_fetches = 0
    lock = Lock()

    def _fetch(url: str) -> dict[str, object]:
        nonlocal jwks_fetches
        if url == DISCOVERY_URL:
            return {"jwks_uri": JWKS_URL}
        if url == JWKS_URL:
            with lock:
                jwks_fetches += 1
            time.sleep(0.02)
            return {"keys": [stale_jwk]}
        raise AssertionError(f"Unexpected URL requested: {url}")

    validator = JwtValidator(auth_settings=_settings(), fetch_json=_fetch)

    async def _run() -> None:
        async def _attempt() -> None:
            with pytest.raises(UnauthorizedError):
                await validator.validate_token(token)

        await asyncio.gather(*(_attempt() for _ in range(5)))

    run_async(_run())

    assert jwks_fetches == 2


def test_after_cooldown_new_key_can_be_picked_up_by_forced_refresh() -> None:
    stale_jwk, _ = generate_rsa_jwk(kid="stale-kid")
    fresh_jwk, fresh_private_key = generate_rsa_jwk(kid="fresh-kid")
    token = issue_access_token(
        private_key=fresh_private_key,
        kid=fresh_jwk["kid"],
        issuer=ISSUER,
        audience="fastapi-api",
        subject="kc-sub-rotated-after-cooldown",
        claims={"azp": "fastapi-web"},
    )
    jwks_fetches = 0

    def _fetch(url: str) -> dict[str, object]:
        nonlocal jwks_fetches
        if url == DISCOVERY_URL:
            return {"jwks_uri": JWKS_URL}
        if url == JWKS_URL:
            jwks_fetches += 1
            if jwks_fetches < 3:
                return {"keys": [stale_jwk]}
            return {"keys": [fresh_jwk]}
        raise AssertionError(f"Unexpected URL requested: {url}")

    validator = JwtValidator(
        auth_settings=_settings(jwks_refresh_cooldown_seconds=0.01),
        fetch_json=_fetch,
    )

    _assert_invalid(token, validator)
    time.sleep(0.02)
    claims = run_async(validator.validate_token(token))

    assert claims["sub"] == "kc-sub-rotated-after-cooldown"
    assert jwks_fetches == 3


def test_failed_forced_refresh_preserves_existing_jwks_cache() -> None:
    known_jwk, known_private_key = generate_rsa_jwk(kid="known-kid")
    unknown_jwk, unknown_private_key = generate_rsa_jwk(kid="unknown-kid")
    known_token = issue_access_token(
        private_key=known_private_key,
        kid=known_jwk["kid"],
        issuer=ISSUER,
        audience="fastapi-api",
        subject="kc-sub-known",
        claims={"azp": "fastapi-web"},
    )
    unknown_token = issue_access_token(
        private_key=unknown_private_key,
        kid=unknown_jwk["kid"],
        issuer=ISSUER,
        audience="fastapi-api",
        subject="kc-sub-unknown",
        claims={"azp": "fastapi-web"},
    )
    jwks_fetches = 0

    def _fetch(url: str) -> dict[str, object]:
        nonlocal jwks_fetches
        if url == DISCOVERY_URL:
            return {"jwks_uri": JWKS_URL}
        if url == JWKS_URL:
            jwks_fetches += 1
            if jwks_fetches == 1:
                return {"keys": [known_jwk]}
            raise RuntimeError("Keycloak unavailable")
        raise AssertionError(f"Unexpected URL requested: {url}")

    validator = JwtValidator(auth_settings=_settings(), fetch_json=_fetch)

    assert run_async(validator.validate_token(known_token))["sub"] == "kc-sub-known"
    _assert_invalid(unknown_token, validator)
    assert run_async(validator.validate_token(known_token))["sub"] == "kc-sub-known"
    assert jwks_fetches == 2

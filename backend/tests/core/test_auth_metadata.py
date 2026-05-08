from __future__ import annotations

import pytest

from app.core.auth_metadata import init_auth_validation
from app.core.config.settings import Settings
from tests.helpers.asyncio_runner import run_async
from tests.helpers.jwt import generate_rsa_jwk

pytestmark = [pytest.mark.security, pytest.mark.auth]

ISSUER = "https://auth.example/realms/main"
DISCOVERY_URL = f"{ISSUER}/.well-known/openid-configuration"
JWKS_URL = f"{ISSUER}/protocol/openid-connect/certs"


def _settings(
    *,
    mode: str = "fail",
    enabled: bool = True,
    jwks_url: str | None = None,
    environment: str = "prod",
) -> Settings:
    return Settings(
        app={"environment": environment},
        api={"docs_enabled": False},
        request_context={"trust_incoming_request_id": False},
        rate_limiting={"enforced_by_edge": True},
        security={
            "outbox_token_encryption_key": (
                "MDEyMzQ1Njc4OWFiY2RlZjAxMjM0NTY3ODlhYmNkZWY="
            ),
        },
        auth={
            "enabled": enabled,
            "issuer_url": ISSUER,
            "audience": "fastapi-api",
            "allowed_authorized_parties": ["fastapi-web"],
            "metadata_validation": mode,
            "jwks_url": jwks_url,
        },
    )


def _valid_discovery(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "issuer": ISSUER,
        "jwks_uri": JWKS_URL,
        "id_token_signing_alg_values_supported": ["RS256"],
    }
    payload.update(overrides)
    return payload


def _valid_jwks() -> dict[str, object]:
    jwk, _ = generate_rsa_jwk(kid="metadata-kid")
    return {"keys": [jwk]}


def _fetcher(
    *,
    discovery: dict[str, object] | None = None,
    jwks: dict[str, object] | None = None,
):
    calls: list[str] = []

    def _fetch(url: str) -> dict[str, object]:
        calls.append(url)
        if url == DISCOVERY_URL:
            return discovery if discovery is not None else _valid_discovery()
        if url == JWKS_URL:
            return jwks if jwks is not None else _valid_jwks()
        raise AssertionError(f"Unexpected URL requested: {url}")

    return _fetch, calls


def test_valid_discovery_and_jwks_pass() -> None:
    fetch, calls = _fetcher()

    run_async(init_auth_validation(_settings(), fetch_json=fetch))

    assert calls == [DISCOVERY_URL, JWKS_URL]


def test_issuer_mismatch_fails_in_fail_mode() -> None:
    fetch, _ = _fetcher(discovery=_valid_discovery(issuer="https://wrong.example"))

    with pytest.raises(RuntimeError, match="OIDC metadata validation failed"):
        run_async(init_auth_validation(_settings(), fetch_json=fetch))


def test_missing_jwks_uri_fails_when_jwks_url_is_not_configured() -> None:
    discovery = _valid_discovery()
    discovery.pop("jwks_uri")
    fetch, _ = _fetcher(discovery=discovery)

    with pytest.raises(RuntimeError, match="OIDC metadata validation failed"):
        run_async(init_auth_validation(_settings(), fetch_json=fetch))


def test_empty_jwks_fails() -> None:
    fetch, _ = _fetcher(jwks={"keys": []})

    with pytest.raises(RuntimeError, match="OIDC metadata validation failed"):
        run_async(init_auth_validation(_settings(), fetch_json=fetch))


def test_jwks_without_rsa_signing_key_fails() -> None:
    fetch, _ = _fetcher(jwks={"keys": [{"kty": "EC", "kid": "ec-kid", "use": "sig"}]})

    with pytest.raises(RuntimeError, match="OIDC metadata validation failed"):
        run_async(init_auth_validation(_settings(), fetch_json=fetch))


def test_missing_kid_in_signing_key_fails() -> None:
    jwk, _ = generate_rsa_jwk(kid="metadata-kid")
    jwk.pop("kid")
    fetch, _ = _fetcher(jwks={"keys": [jwk]})

    with pytest.raises(RuntimeError, match="OIDC metadata validation failed"):
        run_async(init_auth_validation(_settings(), fetch_json=fetch))


def test_warn_mode_logs_and_does_not_raise(monkeypatch) -> None:
    fetch, _ = _fetcher(discovery=_valid_discovery(issuer="https://wrong.example"))
    warnings: list[tuple[str, dict[str, object]]] = []

    class _FakeLogger:
        def warning(self, event: str, **kwargs: object) -> None:
            warnings.append((event, kwargs))

    monkeypatch.setattr(
        "app.core.auth_metadata.get_logger",
        lambda _name: _FakeLogger(),
    )

    run_async(
        init_auth_validation(
            _settings(mode="warn", environment="local"),
            fetch_json=fetch,
        )
    )

    assert warnings == [
        (
            "oidc_metadata_validation_warning",
            {
                "auth_metadata_validation_mode": "warn",
                "error_type": "ValueError",
            },
        )
    ]


def test_disabled_mode_does_not_fetch_metadata() -> None:
    calls: list[str] = []

    def _fetch(url: str) -> dict[str, object]:
        calls.append(url)
        raise AssertionError("metadata must not be fetched")

    run_async(init_auth_validation(_settings(mode="disabled"), fetch_json=_fetch))

    assert calls == []

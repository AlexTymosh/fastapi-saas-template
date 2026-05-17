from __future__ import annotations

import pytest

from app.core.auth_metadata import init_auth_validation
from app.core.config.settings import AuthSettings, Settings
from tests.helpers.asyncio_runner import run_async
from tests.helpers.jwt import generate_rsa_jwk

pytestmark = [pytest.mark.security, pytest.mark.auth]
ISSUER = "https://auth.example/realms/main"
DISCOVERY_URL = f"{ISSUER}/.well-known/openid-configuration"
JWKS_URL = "https://auth.example/realms/main/protocol/openid-connect/certs"


def _settings(
    *,
    metadata_validation: str = "fail",
    jwks_url: str | None = None,
    environment: str = "prod",
) -> Settings:
    return Settings(
        app={"environment": environment},
        api={"docs_enabled": False},
        request_context={"trust_incoming_request_id": False},
        rate_limiting={"enforced_by_edge": True},
        outbox={"invite_delivery_enabled": False},
        auth=AuthSettings(
            enabled=True,
            issuer_url=ISSUER,
            audience="fastapi-api",
            allowed_authorized_parties=["fastapi-web"],
            metadata_validation=metadata_validation,  # type: ignore[arg-type]
            jwks_url=jwks_url,
        ),
    )


def _valid_jwks() -> dict[str, object]:
    jwk, _ = generate_rsa_jwk(kid="metadata-kid")
    return {"keys": [jwk]}


def _fetcher(
    *,
    discovery: dict[str, object] | None = None,
    jwks: dict[str, object] | None = None,
):
    discovery_payload = discovery or {
        "issuer": ISSUER,
        "jwks_uri": JWKS_URL,
        "id_token_signing_alg_values_supported": ["RS256"],
    }
    jwks_payload = jwks or _valid_jwks()
    calls: list[str] = []

    def _fetch(url: str) -> dict[str, object]:
        calls.append(url)
        if url == DISCOVERY_URL:
            return discovery_payload
        if url == JWKS_URL:
            return jwks_payload
        raise AssertionError(f"Unexpected URL requested: {url}")

    return _fetch, calls


def test_valid_discovery_and_jwks_pass() -> None:
    fetch, calls = _fetcher()

    run_async(init_auth_validation(_settings(), fetch_json=fetch))

    assert calls == [DISCOVERY_URL, JWKS_URL]


def test_issuer_mismatch_fails_in_fail_mode() -> None:
    fetch, _ = _fetcher(discovery={"issuer": "https://other", "jwks_uri": JWKS_URL})

    with pytest.raises(RuntimeError, match="Authentication metadata validation failed"):
        run_async(init_auth_validation(_settings(), fetch_json=fetch))


def test_missing_jwks_uri_fails_without_configured_jwks_url() -> None:
    fetch, _ = _fetcher(discovery={"issuer": ISSUER})

    with pytest.raises(RuntimeError):
        run_async(init_auth_validation(_settings(), fetch_json=fetch))


def test_configured_jwks_url_allows_missing_discovery_jwks_uri() -> None:
    fetch, calls = _fetcher(discovery={"issuer": ISSUER})

    run_async(init_auth_validation(_settings(jwks_url=JWKS_URL), fetch_json=fetch))

    assert calls == [DISCOVERY_URL, JWKS_URL]


def test_empty_jwks_fails() -> None:
    fetch, _ = _fetcher(jwks={"keys": []})

    with pytest.raises(RuntimeError):
        run_async(init_auth_validation(_settings(), fetch_json=fetch))


def test_jwks_without_rsa_signing_key_fails() -> None:
    fetch, _ = _fetcher(jwks={"keys": [{"kty": "EC", "kid": "ec-kid"}]})

    with pytest.raises(RuntimeError):
        run_async(init_auth_validation(_settings(), fetch_json=fetch))


def test_missing_kid_in_signing_key_fails() -> None:
    jwk, _ = generate_rsa_jwk(kid="metadata-kid")
    jwk.pop("kid")
    fetch, _ = _fetcher(jwks={"keys": [jwk]})

    with pytest.raises(RuntimeError):
        run_async(init_auth_validation(_settings(), fetch_json=fetch))


def test_warn_mode_logs_and_does_not_raise(monkeypatch) -> None:
    fetch, _ = _fetcher(discovery={"issuer": "https://other", "jwks_uri": JWKS_URL})
    warnings: list[tuple[str, dict[str, object]]] = []

    class FakeLogger:
        def warning(self, event: str, **kwargs: object) -> None:
            warnings.append((event, kwargs))

    monkeypatch.setattr(
        "app.core.auth_metadata.get_logger",
        lambda _name: FakeLogger(),
    )

    run_async(
        init_auth_validation(
            _settings(metadata_validation="warn", environment="local"),
            fetch_json=fetch,
        )
    )

    assert warnings == [
        (
            "auth_metadata_validation_warning",
            {"reason": "ValueError"},
        )
    ]


def test_disabled_mode_does_not_fetch_metadata() -> None:
    calls: list[str] = []

    def _fetch(url: str) -> dict[str, object]:
        calls.append(url)
        raise AssertionError("metadata should not be fetched")

    run_async(
        init_auth_validation(
            _settings(metadata_validation="disabled", environment="local"),
            fetch_json=_fetch,
        )
    )

    assert calls == []

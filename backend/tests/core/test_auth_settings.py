from __future__ import annotations

import pytest

from app.core.config.settings import get_settings
from tests.helpers.settings import reset_settings_cache

pytestmark = [pytest.mark.security, pytest.mark.auth]

FERNET_KEY = "MDEyMzQ1Njc4OWFiY2RlZjAxMjM0NTY3ODlhYmNkZWY="


def _set_base_hardened_env(monkeypatch, *, environment: str) -> None:
    monkeypatch.setenv("APP__ENVIRONMENT", environment)
    monkeypatch.setenv("AUTH__ENABLED", "true")
    monkeypatch.setenv("AUTH__ISSUER_URL", "https://auth.example/realms/main")
    monkeypatch.setenv("AUTH__AUDIENCE", "fastapi-api")
    monkeypatch.setenv("AUTH__ALLOWED_AUTHORIZED_PARTIES", "fastapi-web,fastapi-admin")
    monkeypatch.setenv("AUTH__METADATA_VALIDATION", "fail")
    monkeypatch.setenv("SECURITY__OUTBOX_TOKEN_ENCRYPTION_KEY", FERNET_KEY)
    if environment == "prod":
        monkeypatch.setenv("API__DOCS_ENABLED", "false")
        monkeypatch.setenv("REQUEST_CONTEXT__TRUST_INCOMING_REQUEST_ID", "false")
        monkeypatch.setenv("RATE_LIMITING__ENFORCED_BY_EDGE", "true")


@pytest.mark.parametrize("environment", ["staging", "prod"])
def test_staging_and_prod_require_auth_enabled(monkeypatch, environment: str) -> None:
    _set_base_hardened_env(monkeypatch, environment=environment)
    monkeypatch.setenv("AUTH__ENABLED", "false")

    reset_settings_cache()
    with pytest.raises(ValueError, match="AUTH__ENABLED"):
        get_settings()


@pytest.mark.parametrize(
    "field",
    ["ISSUER_URL", "AUDIENCE", "ALLOWED_AUTHORIZED_PARTIES"],
)
@pytest.mark.parametrize("environment", ["staging", "prod"])
def test_staging_and_prod_require_core_auth_resource_server_settings(
    monkeypatch,
    environment: str,
    field: str,
) -> None:
    _set_base_hardened_env(monkeypatch, environment=environment)
    monkeypatch.delenv(f"AUTH__{field}", raising=False)

    reset_settings_cache()
    with pytest.raises(ValueError, match=f"AUTH__{field}"):
        get_settings()


@pytest.mark.parametrize("environment", ["staging", "prod"])
def test_staging_and_prod_require_metadata_validation_fail(
    monkeypatch,
    environment: str,
) -> None:
    _set_base_hardened_env(monkeypatch, environment=environment)
    monkeypatch.setenv("AUTH__METADATA_VALIDATION", "warn")

    reset_settings_cache()
    with pytest.raises(ValueError, match="AUTH__METADATA_VALIDATION=fail"):
        get_settings()


def test_prod_rejects_http_issuer_url(monkeypatch) -> None:
    _set_base_hardened_env(monkeypatch, environment="prod")
    monkeypatch.setenv("AUTH__ISSUER_URL", "http://auth.example/realms/main")

    reset_settings_cache()
    with pytest.raises(ValueError, match="AUTH__ISSUER_URL must use HTTPS"):
        get_settings()


def test_prod_rejects_http_jwks_url_when_explicitly_configured(monkeypatch) -> None:
    _set_base_hardened_env(monkeypatch, environment="prod")
    monkeypatch.setenv("AUTH__JWKS_URL", "http://auth.example/realms/main/jwks")

    reset_settings_cache()
    with pytest.raises(ValueError, match="AUTH__JWKS_URL must use HTTPS"):
        get_settings()


def test_local_remains_developer_friendly_with_auth_disabled(monkeypatch) -> None:
    monkeypatch.setenv("APP__ENVIRONMENT", "local")
    monkeypatch.setenv("AUTH__ENABLED", "false")
    monkeypatch.delenv("AUTH__ISSUER_URL", raising=False)
    monkeypatch.delenv("AUTH__AUDIENCE", raising=False)
    monkeypatch.delenv("AUTH__ALLOWED_AUTHORIZED_PARTIES", raising=False)

    reset_settings_cache()
    settings = get_settings()

    assert settings.auth.enabled is False
    assert settings.auth.issuer_url is None
    assert settings.auth.audience is None
    assert settings.auth.allowed_authorized_parties == []


def test_auth_settings_normalise_urls_and_allowed_authorized_parties(
    monkeypatch,
) -> None:
    monkeypatch.setenv("AUTH__ISSUER_URL", " https://auth.example/realms/main/ ")
    monkeypatch.setenv("AUTH__JWKS_URL", " https://auth.example/realms/main/jwks/ ")
    monkeypatch.setenv(
        "AUTH__ALLOWED_AUTHORIZED_PARTIES",
        " fastapi-web, ,fastapi-admin ",
    )

    reset_settings_cache()
    settings = get_settings()

    assert settings.auth.issuer_url == "https://auth.example/realms/main"
    assert settings.auth.jwks_url == "https://auth.example/realms/main/jwks"
    assert settings.auth.allowed_authorized_parties == ["fastapi-web", "fastapi-admin"]

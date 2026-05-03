import pytest

from app.core.config.settings import get_settings
from tests.helpers.settings import reset_settings_cache


def test_settings_parses_nested_env(monkeypatch) -> None:
    monkeypatch.setenv("APP__ENVIRONMENT", "test")
    monkeypatch.setenv("LOGGING__AS_JSON", "true")
    monkeypatch.setenv("REQUEST_CONTEXT__HEADER_NAME", "X-Correlation-ID")
    monkeypatch.setenv("VAULT__ENABLED", "true")
    monkeypatch.setenv("DATABASE__URL", "postgresql://localhost/testdb")

    reset_settings_cache()
    settings = get_settings()

    assert settings.app.environment == "test"
    assert settings.logging.as_json is True
    assert settings.request_context.header_name == "X-Correlation-ID"
    assert settings.vault.enabled is True
    assert settings.database.url == "postgresql://localhost/testdb"

    reset_settings_cache()


def test_settings_parse_auth_algorithms_from_csv(monkeypatch) -> None:
    monkeypatch.setenv("AUTH__ALGORITHMS", "RS256")
    monkeypatch.setenv("AUTH__AUDIENCE", "fastapi-api")
    monkeypatch.setenv("AUTH__CLIENT_ID", "fastapi-web")

    reset_settings_cache()
    settings = get_settings()

    assert settings.auth.algorithms == "RS256"
    assert settings.auth.audience == "fastapi-api"
    assert settings.auth.client_id == "fastapi-web"

    reset_settings_cache()


def test_settings_rejects_unsupported_auth_algorithm(monkeypatch) -> None:
    monkeypatch.setenv("AUTH__ALGORITHMS", "RS256,ES256")

    reset_settings_cache()
    with pytest.raises(ValueError, match="AUTH__ALGORITHMS supports only RS256"):
        get_settings()

    reset_settings_cache()


def test_legacy_security_keycloak_env_vars_are_ignored_for_runtime_auth(
    monkeypatch,
) -> None:
    monkeypatch.setenv("AUTH__ISSUER_URL", "http://auth.example/realms/main")
    monkeypatch.setenv("AUTH__CLIENT_ID", "runtime-client")
    monkeypatch.setenv("SECURITY__KEYCLOAK_SERVER_URL", "http://legacy.example")
    monkeypatch.setenv("SECURITY__KEYCLOAK_REALM", "legacy")
    monkeypatch.setenv("SECURITY__KEYCLOAK_CLIENT_ID", "legacy-client")

    reset_settings_cache()
    settings = get_settings()

    assert settings.auth.issuer_url == "http://auth.example/realms/main"
    assert settings.auth.client_id == "runtime-client"
    assert not hasattr(settings.security, "keycloak_server_url")
    assert not hasattr(settings.security, "keycloak_realm")
    assert not hasattr(settings.security, "keycloak_client_id")

    reset_settings_cache()


def test_settings_reads_rate_limiting_nested_env(monkeypatch) -> None:
    monkeypatch.setenv("RATE_LIMITING__ENABLED", "false")
    monkeypatch.setenv("RATE_LIMITING__REDIS_PREFIX", "custom-prefix")
    monkeypatch.setenv("RATE_LIMITING__TRUST_PROXY_HEADERS", "true")
    monkeypatch.setenv("RATE_LIMITING__STORAGE_TIMEOUT_SECONDS", "2.5")

    reset_settings_cache()
    settings = get_settings()

    assert settings.rate_limiting.enabled is False
    assert settings.rate_limiting.redis_prefix == "custom-prefix"
    assert settings.rate_limiting.trust_proxy_headers is True
    assert settings.rate_limiting.storage_timeout_seconds == 2.5

    reset_settings_cache()


def test_settings_reads_outbox_recovery_env(monkeypatch) -> None:
    monkeypatch.setenv("OUTBOX__STALE_PROCESSING_TIMEOUT_SECONDS", "120.5")
    monkeypatch.setenv("OUTBOX__RECOVERY_BATCH_SIZE", "55")

    reset_settings_cache()
    settings = get_settings()

    assert settings.outbox.stale_processing_timeout_seconds == 120.5
    assert settings.outbox.recovery_batch_size == 55

    reset_settings_cache()


def test_prod_requires_auth_enabled(monkeypatch) -> None:
    monkeypatch.setenv("APP__ENVIRONMENT", "prod")
    monkeypatch.setenv("AUTH__ENABLED", "false")
    reset_settings_cache()
    with pytest.raises(ValueError, match="AUTH__ENABLED"):
        get_settings()


def test_staging_requires_auth_enabled(monkeypatch) -> None:
    monkeypatch.setenv("APP__ENVIRONMENT", "staging")
    monkeypatch.setenv("AUTH__ENABLED", "false")
    reset_settings_cache()
    with pytest.raises(ValueError, match="AUTH__ENABLED"):
        get_settings()


def test_prod_rejects_docs_and_request_id_trust(monkeypatch) -> None:
    monkeypatch.setenv("APP__ENVIRONMENT", "prod")
    monkeypatch.setenv("AUTH__ENABLED", "true")
    monkeypatch.setenv("API__DOCS_ENABLED", "true")
    reset_settings_cache()
    with pytest.raises(ValueError, match="API__DOCS_ENABLED"):
        get_settings()
    monkeypatch.setenv("API__DOCS_ENABLED", "false")
    monkeypatch.setenv("REQUEST_CONTEXT__TRUST_INCOMING_REQUEST_ID", "true")
    reset_settings_cache()
    with pytest.raises(ValueError, match="REQUEST_CONTEXT__TRUST_INCOMING_REQUEST_ID"):
        get_settings()


def test_prod_rate_limiting_edge_override_and_outbox_key(monkeypatch) -> None:
    monkeypatch.setenv("APP__ENVIRONMENT", "prod")
    monkeypatch.setenv("AUTH__ENABLED", "true")
    monkeypatch.setenv("API__DOCS_ENABLED", "false")
    monkeypatch.setenv("REQUEST_CONTEXT__TRUST_INCOMING_REQUEST_ID", "false")
    monkeypatch.setenv("RATE_LIMITING__ENABLED", "false")
    monkeypatch.setenv("RATE_LIMITING__ENFORCED_BY_EDGE", "false")
    reset_settings_cache()
    with pytest.raises(ValueError, match="Rate limiting"):
        get_settings()
    monkeypatch.setenv("RATE_LIMITING__ENFORCED_BY_EDGE", "true")
    monkeypatch.delenv("SECURITY__OUTBOX_TOKEN_ENCRYPTION_KEY", raising=False)
    reset_settings_cache()
    with pytest.raises(ValueError, match="OUTBOX_TOKEN_ENCRYPTION_KEY"):
        get_settings()
    monkeypatch.setenv(
        "SECURITY__OUTBOX_TOKEN_ENCRYPTION_KEY",
        "MDEyMzQ1Njc4OWFiY2RlZjAxMjM0NTY3ODlhYmNkZWY=",
    )
    reset_settings_cache()
    settings = get_settings()
    assert settings.app.environment == "prod"

    reset_settings_cache()


def test_dev_requires_outbox_key_when_invite_delivery_enabled(monkeypatch) -> None:
    monkeypatch.setenv("APP__ENVIRONMENT", "dev")
    monkeypatch.setenv("OUTBOX__INVITE_DELIVERY_ENABLED", "true")
    monkeypatch.delenv("SECURITY__OUTBOX_TOKEN_ENCRYPTION_KEY", raising=False)
    reset_settings_cache()
    with pytest.raises(ValueError, match="OUTBOX_TOKEN_ENCRYPTION_KEY"):
        get_settings()


def test_settings_rejects_invalid_fernet_key(monkeypatch) -> None:
    monkeypatch.setenv("SECURITY__OUTBOX_TOKEN_ENCRYPTION_KEY", "invalid-key")
    reset_settings_cache()
    with pytest.raises(ValueError, match="valid Fernet key"):
        get_settings()

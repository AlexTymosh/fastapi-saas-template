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

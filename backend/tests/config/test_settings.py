import pytest

from app.core.config.settings import get_settings


def test_settings_parses_nested_env(monkeypatch) -> None:
    monkeypatch.setenv("APP__ENVIRONMENT", "test")
    monkeypatch.setenv("LOGGING__AS_JSON", "true")
    monkeypatch.setenv("REQUEST_CONTEXT__HEADER_NAME", "X-Correlation-ID")
    monkeypatch.setenv("VAULT__ENABLED", "true")
    monkeypatch.setenv("DATABASE__URL", "postgresql://localhost/testdb")

    get_settings.cache_clear()
    settings = get_settings()

    assert settings.app.environment == "test"
    assert settings.logging.as_json is True
    assert settings.request_context.header_name == "X-Correlation-ID"
    assert settings.vault.enabled is True
    assert settings.database.url == "postgresql://localhost/testdb"

    get_settings.cache_clear()


def test_settings_parse_auth_algorithms_from_csv(monkeypatch) -> None:
    monkeypatch.setenv("AUTH__ALGORITHMS", "RS256")
    monkeypatch.setenv("AUTH__CLIENT_ID", "fastapi-web")

    get_settings.cache_clear()
    settings = get_settings()

    assert settings.auth.algorithms == ["RS256"]
    assert settings.auth.client_id == "fastapi-web"

    get_settings.cache_clear()


def test_settings_rejects_unsupported_auth_algorithm(monkeypatch) -> None:
    monkeypatch.setenv("AUTH__ALGORITHMS", "RS256,ES256")

    get_settings.cache_clear()
    with pytest.raises(ValueError, match="AUTH__ALGORITHMS supports only RS256"):
        get_settings()

    get_settings.cache_clear()


def test_auth_settings_do_not_fall_back_to_legacy_security_client_id(
    monkeypatch,
) -> None:
    monkeypatch.delenv("AUTH__CLIENT_ID", raising=False)
    monkeypatch.setenv("SECURITY__KEYCLOAK_CLIENT_ID", "legacy-client")

    get_settings.cache_clear()
    settings = get_settings()

    assert settings.auth.client_id is None

    get_settings.cache_clear()

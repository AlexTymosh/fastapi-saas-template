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

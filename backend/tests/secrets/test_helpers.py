from app.core.config.settings import Settings
from app.core.secrets.helpers import (
    get_database_url,
    get_keycloak_client_secret,
    get_redis_url,
)


class DummyProvider:
    def __init__(self, values: dict[str, str | None]) -> None:
        self.values = values

    def get(self, key: str) -> str | None:
        return self.values.get(key)


def test_get_database_url_prefers_provider() -> None:
    settings = Settings.model_validate(
        {"database": {"url": "postgresql://from-settings"}}
    )
    provider = DummyProvider({"database/url": "postgresql://from-vault"})

    assert get_database_url(settings, provider) == "postgresql://from-vault"


def test_get_database_url_falls_back_to_settings() -> None:
    settings = Settings.model_validate(
        {"database": {"url": "postgresql://from-settings"}}
    )
    provider = DummyProvider({"database/url": None})

    assert get_database_url(settings, provider) == "postgresql://from-settings"


def test_get_redis_url_prefers_provider() -> None:
    settings = Settings.model_validate({"redis": {"url": "redis://settings"}})
    provider = DummyProvider({"redis/url": "redis://vault"})

    assert get_redis_url(settings, provider) == "redis://vault"


def test_get_keycloak_client_secret_falls_back_to_settings() -> None:
    settings = Settings.model_validate(
        {"security": {"keycloak_client_secret": "settings-secret"}}
    )
    provider = DummyProvider({"security/keycloak_client_secret": None})

    assert get_keycloak_client_secret(settings, provider) == "settings-secret"


def test_get_redis_url_falls_back_to_settings() -> None:
    settings = Settings.model_validate({"redis": {"url": "redis://settings"}})
    provider = DummyProvider({"redis/url": None})

    assert get_redis_url(settings, provider) == "redis://settings"


def test_get_keycloak_client_secret_prefers_provider() -> None:
    settings = Settings.model_validate(
        {"security": {"keycloak_client_secret": "settings-secret"}}
    )
    provider = DummyProvider({"security/keycloak_client_secret": "vault-secret"})

    assert get_keycloak_client_secret(settings, provider) == "vault-secret"


def test_get_database_url_returns_none_if_both_missing() -> None:
    settings = Settings.model_validate({"database": {"url": None}})
    provider = DummyProvider({"database/url": None})

    assert get_database_url(settings, provider) is None

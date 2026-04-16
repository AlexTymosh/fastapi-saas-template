from app.core.config.settings import Settings
from app.core.secrets.env_provider import EnvSecretsProvider


def test_env_provider_returns_database_url() -> None:
    settings = Settings.model_validate(
        {
            "database": {"url": "postgresql+psycopg://user:pass@localhost:5432/app"},
        }
    )

    provider = EnvSecretsProvider(settings)

    assert (
        provider.get("database/url")
        == "postgresql+psycopg://user:pass@localhost:5432/app"
    )


def test_env_provider_returns_redis_url() -> None:
    settings = Settings.model_validate(
        {
            "redis": {"url": "redis://localhost:6379/0"},
        }
    )

    provider = EnvSecretsProvider(settings)

    assert provider.get("redis/url") == "redis://localhost:6379/0"


def test_env_provider_returns_keycloak_client_secret() -> None:
    settings = Settings.model_validate(
        {
            "security": {"keycloak_client_secret": "super-secret"},
        }
    )

    provider = EnvSecretsProvider(settings)

    assert provider.get("security/keycloak_client_secret") == "super-secret"


def test_env_provider_returns_none_for_unknown_key() -> None:
    settings = Settings()
    provider = EnvSecretsProvider(settings)

    assert provider.get("unknown/key") is None

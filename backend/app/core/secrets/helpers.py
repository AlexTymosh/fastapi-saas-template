from __future__ import annotations

from pydantic import SecretStr

from app.core.config.settings import Settings
from app.core.secrets.base import SecretsProvider


def _optional_secret_value(secret: SecretStr | str | None) -> str | None:
    if secret is None:
        return None
    if isinstance(secret, SecretStr):
        return secret.get_secret_value()
    return secret


def get_database_url(
    settings: Settings,
    provider: SecretsProvider,
) -> str | None:
    return provider.get("database/url") or settings.database.url


def get_redis_url(
    settings: Settings,
    provider: SecretsProvider,
) -> str | None:
    return provider.get("redis/url") or settings.redis.url


def get_keycloak_client_secret(
    settings: Settings,
    provider: SecretsProvider,
) -> str | None:
    return provider.get("security/keycloak_client_secret") or _optional_secret_value(
        settings.security.keycloak_client_secret
    )

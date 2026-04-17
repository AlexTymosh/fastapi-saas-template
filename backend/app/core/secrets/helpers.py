from __future__ import annotations

from app.core.config.settings import Settings
from app.core.secrets.base import SecretsProvider


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
    return (
        provider.get("security/keycloak_client_secret")
        or settings.security.keycloak_client_secret
    )

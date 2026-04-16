from __future__ import annotations

from app.core.config.settings import Settings


class EnvSecretsProvider:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def get(self, key: str) -> str | None:
        mapping = {
            "database/url": self.settings.database.url,
            "redis/url": self.settings.redis.url,
            "security/keycloak_client_secret": (
                self.settings.security.keycloak_client_secret
            ),
        }
        return mapping.get(key)

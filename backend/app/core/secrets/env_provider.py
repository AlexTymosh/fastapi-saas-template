from __future__ import annotations

from pydantic import SecretStr

from app.core.config.settings import Settings


def _optional_secret_value(secret: SecretStr | None) -> str | None:
    if secret is None:
        return None
    value = secret.get_secret_value().strip()
    return value or None


class EnvSecretsProvider:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def get(self, key: str) -> str | None:
        mapping = {
            "database/url": self.settings.database.url,
            "redis/url": self.settings.redis.url,
            "security/keycloak_client_secret": _optional_secret_value(
                self.settings.security.keycloak_client_secret
            ),
        }
        return mapping.get(key)

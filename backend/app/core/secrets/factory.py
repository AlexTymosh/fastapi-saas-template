from __future__ import annotations

from app.core.config.settings import Settings
from app.core.secrets.base import SecretsProvider
from app.core.secrets.env_provider import EnvSecretsProvider
from app.core.secrets.vault_provider import VaultSecretsProvider


def build_secrets_provider(settings: Settings) -> SecretsProvider:
    if settings.vault.enabled:
        return VaultSecretsProvider(settings.vault)

    return EnvSecretsProvider(settings)

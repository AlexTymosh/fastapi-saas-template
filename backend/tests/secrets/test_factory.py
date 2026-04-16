from app.core.config.settings import Settings
from app.core.secrets.env_provider import EnvSecretsProvider
from app.core.secrets.factory import build_secrets_provider
from app.core.secrets.vault_provider import VaultSecretsProvider


def test_builds_env_provider_when_vault_disabled() -> None:
    settings = Settings.model_validate(
        {
            "vault": {"enabled": False},
        }
    )

    provider = build_secrets_provider(settings)

    assert isinstance(provider, EnvSecretsProvider)


def test_builds_vault_provider_when_vault_enabled() -> None:
    settings = Settings.model_validate(
        {
            "vault": {"enabled": True},
        }
    )

    provider = build_secrets_provider(settings)

    assert isinstance(provider, VaultSecretsProvider)

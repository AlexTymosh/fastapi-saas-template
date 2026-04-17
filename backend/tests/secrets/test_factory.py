from unittest.mock import patch

from app.core.config.settings import Settings
from app.core.secrets.env_provider import EnvSecretsProvider
from app.core.secrets.factory import build_secrets_provider


def test_builds_env_provider_when_vault_disabled() -> None:
    settings = Settings.model_validate(
        {
            "vault": {"enabled": False},
        }
    )

    provider = build_secrets_provider(settings)

    assert isinstance(provider, EnvSecretsProvider)


@patch("app.core.secrets.factory.VaultSecretsProvider")
def test_builds_vault_provider_when_vault_enabled(
    mock_vault_provider,
) -> None:
    settings = Settings.model_validate(
        {
            "vault": {
                "enabled": True,
                "addr": "http://vault:8200",
                "token": "dev-only-root-token",
            },
        }
    )

    build_secrets_provider(settings)

    mock_vault_provider.assert_called_once_with(settings.vault)

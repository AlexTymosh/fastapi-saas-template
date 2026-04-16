import pytest

from app.core.config.settings import VaultSettings
from app.core.secrets.vault_provider import VaultSecretsProvider


def test_vault_provider_raises_not_implemented() -> None:
    provider = VaultSecretsProvider(VaultSettings())

    with pytest.raises(NotImplementedError, match="not implemented"):
        provider.get("database/url")

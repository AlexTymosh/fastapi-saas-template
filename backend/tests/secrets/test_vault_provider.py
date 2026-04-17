from unittest.mock import Mock, patch

import pytest
from hvac.exceptions import InvalidPath

from app.core.config.settings import VaultSettings
from app.core.secrets.vault_provider import VaultSecretsProvider


@patch("app.core.secrets.vault_provider.hvac.Client")
def test_vault_provider_returns_database_url(mock_client_cls) -> None:
    mock_client = Mock()
    mock_client.is_authenticated.return_value = True
    mock_client.secrets.kv.v2.read_secret_version.return_value = {
        "data": {
            "data": {
                "database_url": "postgresql://vault-db",
                "redis_url": "redis://vault-redis",
                "keycloak_client_secret": "vault-secret",
            }
        }
    }
    mock_client_cls.return_value = mock_client

    provider = VaultSecretsProvider(
        VaultSettings(
            enabled=True,
            addr="http://vault:8200",
            token="dev-only-root-token",
            mount="secret",
            path="fastapi-saas-template",
            auth_method="token",
        )
    )

    assert provider.get("database/url") == "postgresql://vault-db"


@patch("app.core.secrets.vault_provider.hvac.Client")
def test_vault_provider_returns_none_for_unknown_key(mock_client_cls) -> None:
    mock_client = Mock()
    mock_client.is_authenticated.return_value = True
    mock_client.secrets.kv.v2.read_secret_version.return_value = {"data": {"data": {}}}
    mock_client_cls.return_value = mock_client

    provider = VaultSecretsProvider(
        VaultSettings(
            enabled=True,
            addr="http://vault:8200",
            token="dev-only-root-token",
        )
    )

    assert provider.get("unknown/key") is None


@patch("app.core.secrets.vault_provider.hvac.Client")
def test_vault_provider_raises_when_secret_path_missing(mock_client_cls) -> None:
    mock_client = Mock()
    mock_client.is_authenticated.return_value = True
    mock_client.secrets.kv.v2.read_secret_version.side_effect = InvalidPath()
    mock_client_cls.return_value = mock_client

    provider = VaultSecretsProvider(
        VaultSettings(
            enabled=True,
            addr="http://vault:8200",
            token="dev-only-root-token",
            mount="secret",
            path="fastapi-saas-template",
        )
    )

    with pytest.raises(RuntimeError, match="Vault secret not found"):
        provider.get("database/url")


@patch("app.core.secrets.vault_provider.hvac.Client")
def test_vault_provider_raises_when_token_auth_fails(mock_client_cls) -> None:
    mock_client = Mock()
    mock_client.is_authenticated.return_value = False
    mock_client_cls.return_value = mock_client

    provider = VaultSecretsProvider(
        VaultSettings(
            enabled=True,
            addr="http://vault:8200",
            token="bad-token",
            auth_method="token",
        )
    )

    with pytest.raises(RuntimeError, match="token authentication failed"):
        provider.get("database/url")


@patch("app.core.secrets.vault_provider.hvac.Client")
def test_vault_provider_raises_for_missing_approle_credentials(
    mock_client_cls,
) -> None:
    mock_client = Mock()
    mock_client_cls.return_value = mock_client

    provider = VaultSecretsProvider(
        VaultSettings(
            enabled=True,
            addr="http://vault:8200",
            auth_method="approle",
            role_id=None,
            secret_id=None,
        )
    )

    with pytest.raises(RuntimeError, match="requires role_id and secret_id"):
        provider.get("database/url")

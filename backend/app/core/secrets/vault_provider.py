from __future__ import annotations

import hvac
from hvac.exceptions import InvalidPath

from app.core.config.settings import VaultSettings


class VaultSecretsProvider:
    def __init__(self, settings: VaultSettings) -> None:
        self.settings = settings
        self._client: hvac.Client | None = None

    def get(self, key: str) -> str | None:
        secret_data = self._read_secret_data()

        mapping = {
            "database/url": secret_data.get("database_url"),
            "redis/url": secret_data.get("redis_url"),
            "security/keycloak_client_secret": secret_data.get(
                "keycloak_client_secret"
            ),
        }
        return mapping.get(key)

    def _get_client(self) -> hvac.Client:
        if self._client is None:
            self._client = self._build_client()
        return self._client

    def _build_client(self) -> hvac.Client:
        client = hvac.Client(
            url=self.settings.addr,
            token=self.settings.token,
            namespace=self.settings.namespace,
        )

        if self.settings.auth_method == "token":
            if not client.is_authenticated():
                raise RuntimeError("Vault token authentication failed")
            return client

        if self.settings.auth_method == "approle":
            if not self.settings.role_id or not self.settings.secret_id:
                raise RuntimeError("Vault AppRole auth requires role_id and secret_id")

            client.auth.approle.login(
                role_id=self.settings.role_id,
                secret_id=self.settings.secret_id,
            )

            if not client.is_authenticated():
                raise RuntimeError("Vault AppRole authentication failed")
            return client

        raise RuntimeError(
            f"Unsupported Vault auth method: {self.settings.auth_method}"
        )

    def _read_secret_data(self) -> dict[str, str]:
        client = self._get_client()

        try:
            response = client.secrets.kv.v2.read_secret_version(
                path=self.settings.path,
                mount_point=self.settings.mount,
            )
        except InvalidPath as exc:
            raise RuntimeError(
                f"Vault secret not found at {self.settings.mount}/{self.settings.path}"
            ) from exc

        data = response.get("data", {}).get("data")
        if not isinstance(data, dict):
            raise RuntimeError("Vault returned invalid KV v2 secret payload")

        return data

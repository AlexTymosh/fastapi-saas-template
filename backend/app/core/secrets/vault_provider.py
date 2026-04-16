from __future__ import annotations

from app.core.config.settings import VaultSettings


class VaultSecretsProvider:
    def __init__(self, settings: VaultSettings) -> None:
        self.settings = settings

    def get(self, key: str) -> str | None:
        raise NotImplementedError("VaultSecretsProvider is not implemented yet")

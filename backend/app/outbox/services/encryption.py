from __future__ import annotations

from cryptography.fernet import Fernet, InvalidToken

from app.core.config.settings import get_settings


class OutboxTokenEncryptionService:
    def __init__(self, key: str | None = None) -> None:
        if key is None:
            settings = get_settings()
            secret = settings.outbox.token_encryption_key
            key = secret.get_secret_value() if secret is not None else None
            if key is None and settings.app.environment in {"local", "dev", "test"}:
                key = "MDEyMzQ1Njc4OWFiY2RlZjAxMjM0NTY3ODlhYmNkZWY="
        if key is None:
            raise ValueError("OUTBOX__TOKEN_ENCRYPTION_KEY is not configured")
        self._fernet = Fernet(key.encode("utf-8"))

    def encrypt(self, value: str) -> str:
        return self._fernet.encrypt(value.encode("utf-8")).decode("utf-8")

    def decrypt(self, value: str) -> str:
        try:
            return self._fernet.decrypt(value.encode("utf-8")).decode("utf-8")
        except InvalidToken as exc:
            raise ValueError("outbox_payload_decryption_failed") from exc

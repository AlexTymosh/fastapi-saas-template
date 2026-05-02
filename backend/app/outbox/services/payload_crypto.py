from __future__ import annotations

from cryptography.fernet import Fernet, InvalidToken

from app.core.config.settings import Settings, get_settings

_LOCAL_TEST_FALLBACK_FERNET_KEY = "MDEyMzQ1Njc4OWFiY2RlZjAxMjM0NTY3ODlhYmNkZWY="


def resolve_outbox_encryption_key(*, settings: Settings | None = None) -> str:
    current_settings = settings or get_settings()
    configured_key = current_settings.security.outbox_token_encryption_key
    if configured_key:
        return configured_key
    if current_settings.app.environment in {"local", "test"}:
        return _LOCAL_TEST_FALLBACK_FERNET_KEY
    raise ValueError("SECURITY__OUTBOX_TOKEN_ENCRYPTION_KEY must be configured")


class OutboxPayloadCrypto:
    def __init__(self, key: str) -> None:
        try:
            self._fernet = Fernet(key.encode("utf-8"))
        except Exception as exc:
            raise ValueError(
                "Invalid SECURITY__OUTBOX_TOKEN_ENCRYPTION_KEY format"
            ) from exc

    @classmethod
    def from_settings(cls, *, settings: Settings | None = None) -> OutboxPayloadCrypto:
        return cls(resolve_outbox_encryption_key(settings=settings))

    def encrypt_token(self, raw_token: str) -> str:
        return self._fernet.encrypt(raw_token.encode("utf-8")).decode("utf-8")

    def decrypt_token(self, encrypted_raw_token: str) -> str:
        try:
            return self._fernet.decrypt(encrypted_raw_token.encode("utf-8")).decode(
                "utf-8"
            )
        except InvalidToken as exc:
            raise ValueError("outbox_payload_decryption_failed") from exc

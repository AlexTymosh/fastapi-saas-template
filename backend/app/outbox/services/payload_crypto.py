from __future__ import annotations

from base64 import urlsafe_b64decode

from cryptography.fernet import Fernet, InvalidToken

from app.core.config.settings import get_settings

DETERMINISTIC_LOCAL_TEST_FERNET_KEY = "MDEyMzQ1Njc4OWFiY2RlZjAxMjM0NTY3ODlhYmNkZWY="


def validate_fernet_key(key: str) -> str:
    normalized = key.strip()
    try:
        decoded = urlsafe_b64decode(normalized.encode("utf-8"))
    except Exception as exc:
        raise ValueError(
            "SECURITY__OUTBOX_TOKEN_ENCRYPTION_KEY is not a valid Fernet key"
        ) from exc
    if len(decoded) != 32:
        raise ValueError(
            "SECURITY__OUTBOX_TOKEN_ENCRYPTION_KEY is not a valid Fernet key"
        )
    return normalized


def resolve_outbox_encryption_key() -> str:
    settings = get_settings()
    explicit_key = settings.security.outbox_token_encryption_key
    if explicit_key:
        return validate_fernet_key(explicit_key)
    if settings.app.environment in {"local", "test"}:
        return DETERMINISTIC_LOCAL_TEST_FERNET_KEY
    raise ValueError(
        "SECURITY__OUTBOX_TOKEN_ENCRYPTION_KEY is required for invite outbox"
    )


class OutboxPayloadCrypto:
    def __init__(self, key: str) -> None:
        self._fernet = Fernet(validate_fernet_key(key).encode("utf-8"))

    def encrypt_token(self, raw_token: str) -> str:
        return self._fernet.encrypt(raw_token.encode("utf-8")).decode("utf-8")

    def decrypt_token(self, encrypted_raw_token: str) -> str:
        try:
            return self._fernet.decrypt(encrypted_raw_token.encode("utf-8")).decode(
                "utf-8"
            )
        except InvalidToken as exc:
            raise ValueError("outbox_payload_decryption_failed") from exc

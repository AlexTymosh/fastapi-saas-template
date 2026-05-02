from __future__ import annotations

from cryptography.fernet import Fernet, InvalidToken


class OutboxPayloadCrypto:
    def __init__(self, key: str) -> None:
        self._fernet = Fernet(key.encode("utf-8"))

    def encrypt_token(self, raw_token: str) -> str:
        return self._fernet.encrypt(raw_token.encode("utf-8")).decode("utf-8")

    def decrypt_token(self, encrypted_raw_token: str) -> str:
        try:
            return self._fernet.decrypt(encrypted_raw_token.encode("utf-8")).decode(
                "utf-8"
            )
        except InvalidToken as exc:
            raise ValueError("outbox_payload_decryption_failed") from exc

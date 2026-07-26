from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import shutil
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath

from pydantic import SecretStr

from app.privacy.storage.base import (
    StorageAdapter,
    StorageObjectConflictError,
    StoredObject,
)

_FILE_COPY_CHUNK_SIZE = 1024 * 1024
_PUBLISH_RETRY_LIMIT = 3


def _secret_value(secret: str | SecretStr) -> str:
    if isinstance(secret, SecretStr):
        return secret.get_secret_value()
    return secret


def _checksum_and_size(path: Path) -> tuple[str, int]:
    checksum = hashlib.sha256()
    size_bytes = 0
    with path.open("rb") as stream:
        while chunk := stream.read(_FILE_COPY_CHUNK_SIZE):
            checksum.update(chunk)
            size_bytes += len(chunk)
    return checksum.hexdigest(), size_bytes


class LocalStorageAdapter(StorageAdapter):
    def __init__(self, base_path: str, signing_secret: str | SecretStr) -> None:
        self.base_path = Path(base_path).resolve()
        self.signing_secret = _secret_value(signing_secret).encode("utf-8")

    def _resolve(self, key: str) -> Path:
        safe_key = self._validate_key(key)
        path = (self.base_path / safe_key).resolve()
        try:
            path.relative_to(self.base_path)
        except ValueError as exc:
            raise ValueError("Invalid storage key") from exc
        return path

    def _validate_key(self, key: str) -> str:
        if not key or not key.strip():
            raise ValueError("Storage key must not be empty")
        if key != key.strip():
            raise ValueError("Storage key must not have surrounding whitespace")
        if "\\" in key:
            raise ValueError("Storage key must use forward slashes")
        if ":" in key:
            raise ValueError("Storage key must not contain drive or URI separators")
        if "//" in key:
            raise ValueError("Storage key must not contain empty path segments")

        parsed = PurePosixPath(key)
        parts = parsed.parts
        if (
            parsed.is_absolute()
            or not parts
            or any(part in {"", ".", ".."} for part in parts)
        ):
            raise ValueError("Invalid storage key")
        return "/".join(parts)

    def put_bytes(self, key: str, data: bytes, content_type: str) -> StoredObject:
        path = self._resolve(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return StoredObject(key=key, content_type=content_type, size_bytes=len(data))

    def put_file(self, key: str, path: Path, content_type: str) -> StoredObject:
        target = self._resolve(key)
        target.parent.mkdir(parents=True, exist_ok=True)
        with path.open("rb") as source, target.open("wb") as destination:
            shutil.copyfileobj(source, destination, length=_FILE_COPY_CHUNK_SIZE)
        return StoredObject(
            key=key,
            content_type=content_type,
            size_bytes=target.stat().st_size,
        )

    def put_file_if_absent(
        self,
        key: str,
        path: Path,
        content_type: str,
        *,
        checksum_sha256: str,
    ) -> StoredObject:
        """Atomically publish a complete file without replacing an existing key."""

        target = self._resolve(key)
        target.parent.mkdir(parents=True, exist_ok=True)
        staged_checksum, staged_size = _checksum_and_size(path)
        if staged_checksum != checksum_sha256:
            raise ValueError("Prepared storage file checksum changed")

        for _ in range(_PUBLISH_RETRY_LIMIT):
            try:
                os.link(path, target)
            except FileExistsError:
                try:
                    existing_checksum, existing_size = _checksum_and_size(target)
                except FileNotFoundError:
                    continue
                if (
                    existing_checksum == staged_checksum
                    and existing_size == staged_size
                ):
                    return StoredObject(
                        key=key,
                        content_type=content_type,
                        size_bytes=existing_size,
                    )
                raise StorageObjectConflictError(
                    "Immutable storage key already contains different bytes"
                ) from None
            else:
                return StoredObject(
                    key=key,
                    content_type=content_type,
                    size_bytes=staged_size,
                )

        raise StorageObjectConflictError(
            "Immutable storage key changed during publication"
        )

    def get_bytes(self, key: str) -> bytes:
        return self._resolve(key).read_bytes()

    def exists(self, key: str) -> bool:
        return self._resolve(key).exists()

    def delete(self, key: str) -> None:
        path = self._resolve(key)
        if path.exists():
            path.unlink()

    def generate_download_url(self, key: str, expires_in_seconds: int) -> str:
        safe_key = self._validate_key(key)
        payload = {
            "k": safe_key,
            "exp": int(datetime.now(UTC).timestamp()) + expires_in_seconds,
        }
        payload_bytes = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        payload_b64 = base64.urlsafe_b64encode(payload_bytes).decode("ascii")
        signature = hmac.new(
            self.signing_secret,
            payload_bytes,
            hashlib.sha256,
        ).hexdigest()
        return f"local://privacy-export/{payload_b64}.{signature}"

    def verify_download_url(self, token: str, *, expected_key: str) -> bool:
        prefix = "local://privacy-export/"
        if not token.startswith(prefix):
            return False
        body = token[len(prefix) :]
        if "." not in body:
            return False
        payload_b64, signature = body.rsplit(".", 1)
        try:
            payload_bytes = base64.urlsafe_b64decode(payload_b64.encode("ascii"))
            payload = json.loads(payload_bytes)
        except Exception:
            return False
        expected = hmac.new(
            self.signing_secret,
            payload_bytes,
            hashlib.sha256,
        ).hexdigest()
        if not hmac.compare_digest(expected, signature):
            return False
        if payload.get("k") != expected_key:
            return False
        return int(payload.get("exp", 0)) > int(datetime.now(UTC).timestamp())

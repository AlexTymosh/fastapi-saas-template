from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import shutil
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from uuid import uuid4

from pydantic import SecretStr

from app.privacy.storage.base import (
    StorageAdapter,
    StorageObjectConflictError,
    StorageObjectState,
    StoragePublicationReservation,
    StoredObject,
)

_FILE_COPY_CHUNK_SIZE = 1024 * 1024
_PUBLISH_RETRY_LIMIT = 3
_PUBLISHED_OBJECT_NAME = "object"
_RESERVATION_NAME = "reservation"


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

    def reserve_file_publication(
        self,
        key: str,
        *,
        owner_token: str,
    ) -> StoragePublicationReservation:
        """Create a cross-process filesystem reservation for a logical key."""

        target = self._resolve(key)
        target.parent.mkdir(parents=True, exist_ok=True)

        for _ in range(_PUBLISH_RETRY_LIMIT):
            staged = target.parent / f".{target.name}.{uuid4().hex}.reservation"
            staged.mkdir()
            (staged / _RESERVATION_NAME).write_text(
                owner_token,
                encoding="utf-8",
            )
            try:
                staged.rename(target)
            except OSError:
                shutil.rmtree(staged, ignore_errors=True)
            else:
                return StoragePublicationReservation(
                    key=key,
                    owner_token=owner_token,
                    revision=owner_token,
                )

            reservation_path = target / _RESERVATION_NAME
            object_path = target / _PUBLISHED_OBJECT_NAME
            if object_path.is_file() or target.is_file():
                raise StorageObjectConflictError(
                    "Storage key already contains a published object"
                )
            try:
                existing_owner = reservation_path.read_text(encoding="utf-8")
            except FileNotFoundError:
                continue
            if existing_owner == owner_token:
                return StoragePublicationReservation(
                    key=key,
                    owner_token=owner_token,
                    revision=owner_token,
                )
            raise StorageObjectConflictError(
                "Storage key is reserved by another publisher"
            )

        raise StorageObjectConflictError(
            "Storage publication reservation did not settle"
        )

    def publish_reserved_file(
        self,
        reservation: StoragePublicationReservation,
        path: Path,
        content_type: str,
        *,
        checksum_sha256: str,
    ) -> StoredObject:
        """Publish only while the caller still owns the filesystem reservation."""

        target = self._resolve(reservation.key)
        reservation_path = target / _RESERVATION_NAME
        object_path = target / _PUBLISHED_OBJECT_NAME
        staged_checksum, staged_size = _checksum_and_size(path)
        if staged_checksum != checksum_sha256:
            raise ValueError("Prepared storage file checksum changed")

        try:
            existing_owner = reservation_path.read_text(encoding="utf-8")
        except (FileNotFoundError, NotADirectoryError) as exc:
            raise StorageObjectConflictError(
                "Storage publication reservation is no longer active"
            ) from exc
        if (
            existing_owner != reservation.owner_token
            or reservation.revision != reservation.owner_token
        ):
            raise StorageObjectConflictError(
                "Storage publication reservation is no longer owned"
            )

        try:
            os.link(path, object_path)
        except FileExistsError:
            existing_checksum, existing_size = _checksum_and_size(object_path)
            if existing_checksum != staged_checksum or existing_size != staged_size:
                raise StorageObjectConflictError(
                    "Storage key already contains different bytes"
                ) from None
        except FileNotFoundError as exc:
            raise StorageObjectConflictError(
                "Storage publication reservation was removed"
            ) from exc

        try:
            reservation_path.unlink()
        except FileNotFoundError:
            state = self.inspect_file(
                reservation.key,
                checksum_sha256=checksum_sha256,
                size_bytes=staged_size,
            )
            if state != StorageObjectState.MATCHING:
                raise StorageObjectConflictError(
                    "Storage publication lost its cleanup race"
                ) from None

        return StoredObject(
            key=reservation.key,
            content_type=content_type,
            size_bytes=staged_size,
        )

    def cancel_file_publication(
        self,
        reservation: StoragePublicationReservation,
    ) -> None:
        target = self._resolve(reservation.key)
        reservation_path = target / _RESERVATION_NAME
        object_path = target / _PUBLISHED_OBJECT_NAME
        try:
            owner_token = reservation_path.read_text(encoding="utf-8")
        except (FileNotFoundError, NotADirectoryError):
            return
        if owner_token != reservation.owner_token or object_path.exists():
            return
        self._remove_target_atomically(target)

    def inspect_file(
        self,
        key: str,
        *,
        checksum_sha256: str,
        size_bytes: int,
    ) -> StorageObjectState:
        target = self._resolve(key)
        if not target.exists():
            return StorageObjectState.MISSING
        if target.is_dir():
            object_path = target / _PUBLISHED_OBJECT_NAME
            if not object_path.is_file():
                if (target / _RESERVATION_NAME).is_file():
                    return StorageObjectState.RESERVED
                return StorageObjectState.CONFLICT
        else:
            object_path = target

        existing_checksum, existing_size = _checksum_and_size(object_path)
        if existing_checksum == checksum_sha256 and existing_size == size_bytes:
            return StorageObjectState.MATCHING
        return StorageObjectState.CONFLICT

    def get_bytes(self, key: str) -> bytes:
        target = self._resolve(key)
        object_path = target / _PUBLISHED_OBJECT_NAME if target.is_dir() else target
        return object_path.read_bytes()

    def exists(self, key: str) -> bool:
        target = self._resolve(key)
        if target.is_dir():
            return (target / _PUBLISHED_OBJECT_NAME).is_file()
        return target.is_file()

    def delete(self, key: str) -> None:
        target = self._resolve(key)
        self._remove_target_atomically(target)

    @staticmethod
    def _remove_target_atomically(target: Path) -> None:
        if not target.exists():
            return
        quarantine = target.parent / f".{target.name}.{uuid4().hex}.deleted"
        try:
            target.rename(quarantine)
        except FileNotFoundError:
            return
        if quarantine.is_dir():
            shutil.rmtree(quarantine)
        else:
            quarantine.unlink(missing_ok=True)

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

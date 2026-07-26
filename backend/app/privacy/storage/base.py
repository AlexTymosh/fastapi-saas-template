from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Protocol


@dataclass(frozen=True)
class StoredObject:
    key: str
    content_type: str
    size_bytes: int


class StorageObjectConflictError(RuntimeError):
    """Raised when an immutable object key already contains different bytes."""


class StorageObjectState(StrEnum):
    MISSING = "missing"
    RESERVED = "reserved"
    MATCHING = "matching"
    CONFLICT = "conflict"


@dataclass(frozen=True)
class StoragePublicationReservation:
    key: str
    owner_token: str
    revision: str


class StorageAdapter(Protocol):
    def put_bytes(self, key: str, data: bytes, content_type: str) -> StoredObject: ...

    def put_file(self, key: str, path: Path, content_type: str) -> StoredObject: ...

    def reserve_file_publication(
        self,
        key: str,
        *,
        owner_token: str,
    ) -> StoragePublicationReservation: ...

    def publish_reserved_file(
        self,
        reservation: StoragePublicationReservation,
        path: Path,
        content_type: str,
        *,
        checksum_sha256: str,
    ) -> StoredObject: ...

    def cancel_file_publication(
        self,
        reservation: StoragePublicationReservation,
    ) -> None: ...

    def inspect_file(
        self,
        key: str,
        *,
        checksum_sha256: str,
        size_bytes: int,
    ) -> StorageObjectState: ...

    def get_bytes(self, key: str) -> bytes: ...

    def exists(self, key: str) -> bool: ...

    def delete(self, key: str) -> None: ...

    def generate_download_url(self, key: str, expires_in_seconds: int) -> str: ...

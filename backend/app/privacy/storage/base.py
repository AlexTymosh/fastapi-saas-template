from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol


@dataclass(frozen=True)
class StoredObject:
    key: str
    content_type: str
    size_bytes: int


class StorageAdapter(Protocol):
    def put_bytes(self, key: str, data: bytes, content_type: str) -> StoredObject: ...

    def put_file(self, key: str, path: Path, content_type: str) -> StoredObject: ...

    def get_bytes(self, key: str) -> bytes: ...

    def exists(self, key: str) -> bool: ...

    def delete(self, key: str) -> None: ...

    def generate_download_url(self, key: str, expires_in_seconds: int) -> str: ...

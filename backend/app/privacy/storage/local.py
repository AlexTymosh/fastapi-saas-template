from __future__ import annotations

from pathlib import Path

from app.privacy.storage.base import StorageAdapter, StoredObject


class LocalStorageAdapter(StorageAdapter):
    def __init__(self, base_path: str) -> None:
        self.base_path = Path(base_path).resolve()
        self.base_path.mkdir(parents=True, exist_ok=True)

    def _resolve(self, key: str) -> Path:
        safe_key = key.replace("..", "").strip("/")
        path = (self.base_path / safe_key).resolve()
        if not str(path).startswith(str(self.base_path)):
            raise ValueError("Invalid storage key")
        path.parent.mkdir(parents=True, exist_ok=True)
        return path

    def put_bytes(self, key: str, data: bytes, content_type: str) -> StoredObject:
        path = self._resolve(key)
        path.write_bytes(data)
        return StoredObject(key=key, content_type=content_type, size_bytes=len(data))

    def get_bytes(self, key: str) -> bytes:
        return self._resolve(key).read_bytes()

    def exists(self, key: str) -> bool:
        return self._resolve(key).exists()

    def delete(self, key: str) -> None:
        path = self._resolve(key)
        if path.exists():
            path.unlink()

    def generate_download_url(self, key: str, expires_in_seconds: int) -> str:
        return f"local://privacy-export/{key}?ttl={expires_in_seconds}"

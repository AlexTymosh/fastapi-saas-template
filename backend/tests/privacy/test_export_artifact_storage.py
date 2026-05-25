from __future__ import annotations

import time

import pytest

from app.privacy.storage.local import LocalStorageAdapter


def test_local_storage_rejects_unsafe_paths(tmp_path) -> None:
    storage = LocalStorageAdapter(str(tmp_path), "test-secret")
    for key in ["../secret", "..\\secret", "/absolute/path", ""]:
        with pytest.raises(ValueError):
            storage.put_bytes(key, b"x", "application/octet-stream")


def test_local_storage_put_get_and_signed_url(tmp_path) -> None:
    storage = LocalStorageAdapter(str(tmp_path), "test-secret")
    key = "nested/file.zip"
    storage.put_bytes(key, b"payload", "application/zip")
    assert storage.exists(key)
    assert storage.get_bytes(key) == b"payload"
    token = storage.generate_download_url(key, 2)
    assert storage.verify_download_url(token, expected_key=key)
    tampered = token[:-1] + ("0" if token[-1] != "0" else "1")
    assert not storage.verify_download_url(tampered, expected_key=key)
    time.sleep(2)
    assert not storage.verify_download_url(token, expected_key=key)

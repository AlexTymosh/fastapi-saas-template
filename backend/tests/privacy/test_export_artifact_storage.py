from __future__ import annotations

import pytest

from app.privacy.storage.local import LocalStorageAdapter


def test_local_storage_rejects_unsafe_paths(tmp_path) -> None:
    storage = LocalStorageAdapter(str(tmp_path), "test-secret")
    for key in [
        "../secret",
        "..\\secret",
        "/absolute/path",
        "",
        ".",
        "nested/../secret",
        "nested//secret",
        " C:/secret ",
        "C:/secret",
    ]:
        with pytest.raises(ValueError):
            storage.put_bytes(key, b"x", "application/octet-stream")


def test_local_storage_constructor_does_not_create_runtime_directory(tmp_path) -> None:
    base_path = tmp_path / "privacy-exports"
    LocalStorageAdapter(str(base_path), "test-secret")
    assert not base_path.exists()


def test_local_storage_put_get_and_signed_url(tmp_path) -> None:
    storage = LocalStorageAdapter(str(tmp_path), "test-secret")
    key = "nested/file.zip"
    storage.put_bytes(key, b"payload", "application/zip")
    assert storage.exists(key)
    assert storage.get_bytes(key) == b"payload"
    token = storage.generate_download_url(key, 60)
    assert storage.verify_download_url(token, expected_key=key)
    tampered = token[:-1] + ("0" if token[-1] != "0" else "1")
    assert not storage.verify_download_url(tampered, expected_key=key)
    expired = storage.generate_download_url(key, -1)
    assert not storage.verify_download_url(expired, expected_key=key)

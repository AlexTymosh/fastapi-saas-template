from __future__ import annotations

import hashlib

import pytest

from app.privacy.storage.base import (
    StorageObjectConflictError,
    StorageObjectState,
)
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


def test_local_storage_immutable_publish_never_replaces_existing_bytes(
    tmp_path,
) -> None:
    storage = LocalStorageAdapter(str(tmp_path / "storage"), "test-secret")
    key = "exports/artifact/archive.zip"
    first_path = tmp_path / "first.zip"
    first_payload = b"first archive"
    first_path.write_bytes(first_payload)
    first_checksum = hashlib.sha256(first_payload).hexdigest()

    reservation = storage.reserve_file_publication(
        key,
        owner_token="first-owner",
    )
    storage.publish_reserved_file(
        reservation,
        first_path,
        "application/zip",
        checksum_sha256=first_checksum,
    )
    storage.cancel_file_publication(reservation)

    with pytest.raises(StorageObjectConflictError):
        storage.reserve_file_publication(
            key,
            owner_token="different-owner",
        )

    assert (
        storage.inspect_file(
            key,
            checksum_sha256=first_checksum,
            size_bytes=len(first_payload),
        )
        == StorageObjectState.MATCHING
    )
    assert storage.get_bytes(key) == first_payload


def test_local_storage_cleanup_fences_reserved_publication(tmp_path) -> None:
    storage = LocalStorageAdapter(str(tmp_path / "storage"), "test-secret")
    key = "exports/artifact/archive.zip"
    archive_path = tmp_path / "archive.zip"
    payload = b"privacy export archive"
    archive_path.write_bytes(payload)
    checksum = hashlib.sha256(payload).hexdigest()
    reservation = storage.reserve_file_publication(
        key,
        owner_token="stale-owner",
    )

    storage.delete(key)

    with pytest.raises(StorageObjectConflictError):
        storage.publish_reserved_file(
            reservation,
            archive_path,
            "application/zip",
            checksum_sha256=checksum,
        )

    assert not storage.exists(key)

from __future__ import annotations

import hashlib
import os
import threading
from concurrent.futures import ThreadPoolExecutor

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


def test_local_guarded_cleanup_preserves_concurrent_matching_publication(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    storage = LocalStorageAdapter(str(tmp_path / "storage"), "test-secret")
    key = "exports/artifact/archive.zip"
    archive_path = tmp_path / "archive.zip"
    payload = b"privacy export archive"
    archive_path.write_bytes(payload)
    checksum = hashlib.sha256(payload).hexdigest()
    reservation = storage.reserve_file_publication(
        key,
        owner_token="publisher",
    )
    publication_holds_lock = threading.Event()
    release_publication = threading.Event()
    cleanup_started = threading.Event()

    original_link = os.link

    def _controlled_link(source, destination) -> None:
        publication_holds_lock.set()
        if not release_publication.wait(timeout=10):
            raise TimeoutError("Timed out waiting to release publication")
        original_link(source, destination)

    monkeypatch.setattr("app.privacy.storage.local.os.link", _controlled_link)

    def _publish() -> None:
        storage.publish_reserved_file(
            reservation,
            archive_path,
            "application/zip",
            checksum_sha256=checksum,
        )

    def _guarded_cleanup() -> StorageObjectState:
        cleanup_started.set()
        return storage.delete_file_if_not_matching(
            key,
            checksum_sha256=checksum,
            size_bytes=len(payload),
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        publication = executor.submit(_publish)
        assert publication_holds_lock.wait(timeout=10)
        cleanup = executor.submit(_guarded_cleanup)
        assert cleanup_started.wait(timeout=10)
        assert not cleanup.done()
        release_publication.set()
        publication.result(timeout=10)
        cleanup_state = cleanup.result(timeout=10)

    assert cleanup_state == StorageObjectState.MATCHING
    assert storage.get_bytes(key) == payload

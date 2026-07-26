from __future__ import annotations

import base64
import hashlib
import io

import boto3
import pytest
from botocore.config import Config
from botocore.response import StreamingBody
from botocore.stub import ANY, Stubber

from app.privacy.storage.base import StorageObjectConflictError
from app.privacy.storage.s3 import S3CompatibleStorageAdapter

pytestmark = [pytest.mark.privacy, pytest.mark.security]


def _stubbed_storage(monkeypatch: pytest.MonkeyPatch) -> S3CompatibleStorageAdapter:
    client = boto3.client(
        "s3",
        region_name="eu-west-2",
        aws_access_key_id="access-key",
        aws_secret_access_key="secret-key",
        config=Config(signature_version="s3v4"),
    )
    monkeypatch.setattr("app.privacy.storage.s3.boto3.client", lambda *a, **k: client)
    return S3CompatibleStorageAdapter(
        bucket_name="privacy-exports",
        region_name="eu-west-2",
        endpoint_url="https://s3.example.test",
        access_key_id="access-key",
        secret_access_key="secret-key",
        key_prefix="privacy-exports",
    )


def test_s3_storage_put_get_exists_delete_and_presigned_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    storage = _stubbed_storage(monkeypatch)
    client = storage.client
    key = "exports/artifact.zip"
    object_key = "privacy-exports/exports/artifact.zip"

    with Stubber(client) as stubber:
        stubber.add_response(
            "put_object",
            {"ETag": "etag"},
            {
                "Bucket": "privacy-exports",
                "Key": object_key,
                "Body": b"payload",
                "ContentType": "application/zip",
                "Metadata": {"privacy-artifact": "true"},
                "ServerSideEncryption": "AES256",
            },
        )
        stubber.add_response(
            "head_object",
            {"ContentLength": 7},
            {"Bucket": "privacy-exports", "Key": object_key},
        )
        stubber.add_response(
            "get_object",
            {"Body": StreamingBody(io.BytesIO(b"payload"), 7)},
            {"Bucket": "privacy-exports", "Key": object_key},
        )
        stubber.add_response(
            "delete_object",
            {},
            {"Bucket": "privacy-exports", "Key": object_key},
        )

        stored = storage.put_bytes(key, b"payload", "application/zip")
        assert stored.key == key
        assert stored.size_bytes == 7
        assert storage.exists(key)
        assert storage.get_bytes(key) == b"payload"
        storage.delete(key)

    url = storage.generate_download_url(key, 60)

    assert "X-Amz-Signature=" in url
    assert object_key in url


def test_s3_storage_exists_returns_false_for_missing_object(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    storage = _stubbed_storage(monkeypatch)
    client = storage.client

    with Stubber(client) as stubber:
        stubber.add_client_error(
            "head_object",
            service_error_code="404",
            http_status_code=404,
            expected_params={
                "Bucket": "privacy-exports",
                "Key": "privacy-exports/exports/missing.zip",
            },
        )

        assert storage.exists("exports/missing.zip") is False


def test_s3_storage_rejects_unsafe_storage_keys(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    storage = _stubbed_storage(monkeypatch)

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


def test_s3_storage_immutable_publish_uses_conditional_put(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    storage = _stubbed_storage(monkeypatch)
    client = storage.client
    path = tmp_path / "archive.zip"
    payload = b"privacy export archive"
    path.write_bytes(payload)
    checksum = hashlib.sha256(payload).hexdigest()
    checksum_base64 = base64.b64encode(bytes.fromhex(checksum)).decode("ascii")
    object_key = "privacy-exports/exports/artifact.zip"

    with Stubber(client) as stubber:
        stubber.add_response(
            "put_object",
            {"ETag": "etag"},
            {
                "Bucket": "privacy-exports",
                "Key": object_key,
                "Body": ANY,
                "ContentLength": len(payload),
                "ContentType": "application/zip",
                "Metadata": {
                    "privacy-artifact": "true",
                    "checksum-sha256": checksum,
                },
                "IfNoneMatch": "*",
                "ChecksumSHA256": checksum_base64,
                "ServerSideEncryption": "AES256",
            },
        )

        stored = storage.put_file_if_absent(
            "exports/artifact.zip",
            path,
            "application/zip",
            checksum_sha256=checksum,
        )

    assert stored.size_bytes == len(payload)


def test_s3_storage_immutable_publish_reuses_only_matching_object(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    storage = _stubbed_storage(monkeypatch)
    client = storage.client
    path = tmp_path / "archive.zip"
    payload = b"privacy export archive"
    path.write_bytes(payload)
    checksum = hashlib.sha256(payload).hexdigest()
    object_key = "privacy-exports/exports/artifact.zip"

    expected_put = {
        "Bucket": "privacy-exports",
        "Key": object_key,
        "Body": ANY,
        "ContentLength": len(payload),
        "ContentType": "application/zip",
        "Metadata": {
            "privacy-artifact": "true",
            "checksum-sha256": checksum,
        },
        "IfNoneMatch": "*",
        "ChecksumSHA256": base64.b64encode(bytes.fromhex(checksum)).decode("ascii"),
        "ServerSideEncryption": "AES256",
    }

    with Stubber(client) as stubber:
        stubber.add_client_error(
            "put_object",
            service_error_code="PreconditionFailed",
            http_status_code=412,
            expected_params=expected_put,
        )
        stubber.add_response(
            "head_object",
            {
                "ContentLength": len(payload),
                "Metadata": {"checksum-sha256": checksum},
            },
            {"Bucket": "privacy-exports", "Key": object_key},
        )

        stored = storage.put_file_if_absent(
            "exports/artifact.zip",
            path,
            "application/zip",
            checksum_sha256=checksum,
        )

    assert stored.size_bytes == len(payload)

    with Stubber(client) as stubber:
        stubber.add_client_error(
            "put_object",
            service_error_code="PreconditionFailed",
            http_status_code=412,
            expected_params=expected_put,
        )
        stubber.add_response(
            "head_object",
            {
                "ContentLength": len(payload),
                "Metadata": {"checksum-sha256": "0" * 64},
            },
            {"Bucket": "privacy-exports", "Key": object_key},
        )

        with pytest.raises(StorageObjectConflictError):
            storage.put_file_if_absent(
                "exports/artifact.zip",
                path,
                "application/zip",
                checksum_sha256=checksum,
            )


def test_s3_storage_retries_conditional_request_conflict(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    storage = _stubbed_storage(monkeypatch)
    client = storage.client
    path = tmp_path / "archive.zip"
    payload = b"privacy export archive"
    path.write_bytes(payload)
    checksum = hashlib.sha256(payload).hexdigest()
    expected_put = {
        "Bucket": "privacy-exports",
        "Key": "privacy-exports/exports/artifact.zip",
        "Body": ANY,
        "ContentLength": len(payload),
        "ContentType": "application/zip",
        "Metadata": {
            "privacy-artifact": "true",
            "checksum-sha256": checksum,
        },
        "IfNoneMatch": "*",
        "ChecksumSHA256": base64.b64encode(bytes.fromhex(checksum)).decode("ascii"),
        "ServerSideEncryption": "AES256",
    }

    with Stubber(client) as stubber:
        stubber.add_client_error(
            "put_object",
            service_error_code="ConditionalRequestConflict",
            http_status_code=409,
            expected_params=expected_put,
        )
        stubber.add_response(
            "put_object",
            {"ETag": "etag"},
            expected_put,
        )

        stored = storage.put_file_if_absent(
            "exports/artifact.zip",
            path,
            "application/zip",
            checksum_sha256=checksum,
        )

    assert stored.size_bytes == len(payload)

from __future__ import annotations

import base64
from pathlib import Path, PurePosixPath
from typing import Any

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

from app.privacy.storage.base import StorageObjectConflictError, StoredObject


class S3CompatibleStorageAdapter:
    """S3-compatible private object storage adapter for privacy export artifacts.

    The adapter stores objects in a private bucket and returns short-lived
    presigned GET URLs. It deliberately never exposes bucket names or raw object
    keys through API response models; callers store only the logical storage key
    in the export_artifacts table.
    """

    def __init__(
        self,
        *,
        bucket_name: str,
        region_name: str,
        endpoint_url: str | None = None,
        access_key_id: str | None = None,
        secret_access_key: str | None = None,
        key_prefix: str = "privacy-exports",
        server_side_encryption: str | None = "AES256",
        sse_kms_key_id: str | None = None,
        addressing_style: str = "virtual",
        connect_timeout_seconds: float = 3.0,
        read_timeout_seconds: float = 10.0,
        max_attempts: int = 3,
    ) -> None:
        self.bucket_name = self._normalise_required("bucket_name", bucket_name)
        self.key_prefix = self._normalise_prefix(key_prefix)
        self.server_side_encryption = self._normalise_optional(server_side_encryption)
        self.sse_kms_key_id = self._normalise_optional(sse_kms_key_id)
        self.max_conditional_write_attempts = max(1, max_attempts)
        self.client = boto3.client(
            "s3",
            endpoint_url=self._normalise_optional(endpoint_url),
            region_name=self._normalise_required("region_name", region_name),
            aws_access_key_id=self._normalise_optional(access_key_id),
            aws_secret_access_key=self._normalise_optional(secret_access_key),
            config=Config(
                signature_version="s3v4",
                connect_timeout=connect_timeout_seconds,
                read_timeout=read_timeout_seconds,
                retries={"max_attempts": max_attempts, "mode": "standard"},
                s3={"addressing_style": addressing_style},
            ),
        )

    def put_bytes(self, key: str, data: bytes, content_type: str) -> StoredObject:
        object_key = self._object_key(key)
        params: dict[str, Any] = {
            "Bucket": self.bucket_name,
            "Key": object_key,
            "Body": data,
            "ContentType": content_type,
            "Metadata": {"privacy-artifact": "true"},
        }
        self._add_server_side_encryption(params)
        self.client.put_object(**params)
        return StoredObject(key=key, content_type=content_type, size_bytes=len(data))

    def put_file(self, key: str, path: Path, content_type: str) -> StoredObject:
        object_key = self._object_key(key)
        extra_args: dict[str, Any] = {
            "ContentType": content_type,
            "Metadata": {"privacy-artifact": "true"},
        }
        self._add_server_side_encryption(extra_args)
        with path.open("rb") as body:
            self.client.upload_fileobj(
                body,
                self.bucket_name,
                object_key,
                ExtraArgs=extra_args,
            )
        return StoredObject(
            key=key,
            content_type=content_type,
            size_bytes=path.stat().st_size,
        )

    def put_file_if_absent(
        self,
        key: str,
        path: Path,
        content_type: str,
        *,
        checksum_sha256: str,
    ) -> StoredObject:
        """Publish with an S3 precondition that prevents lease-stale overwrite."""

        object_key = self._object_key(key)
        size_bytes = path.stat().st_size
        checksum_base64 = self._sha256_base64(checksum_sha256)
        params: dict[str, Any] = {
            "Bucket": self.bucket_name,
            "Key": object_key,
            "ContentLength": size_bytes,
            "ContentType": content_type,
            "Metadata": {
                "privacy-artifact": "true",
                "checksum-sha256": checksum_sha256,
            },
            "IfNoneMatch": "*",
            "ChecksumSHA256": checksum_base64,
        }
        self._add_server_side_encryption(params)

        for _ in range(self.max_conditional_write_attempts):
            try:
                with path.open("rb") as body:
                    self.client.put_object(Body=body, **params)
            except ClientError as exc:
                if self._is_precondition_failure(exc):
                    existing_matches = self._existing_file_matches(
                        object_key=object_key,
                        checksum_sha256=checksum_sha256,
                        size_bytes=size_bytes,
                    )
                    if existing_matches is True:
                        return StoredObject(
                            key=key,
                            content_type=content_type,
                            size_bytes=size_bytes,
                        )
                    if existing_matches is False:
                        raise StorageObjectConflictError(
                            "Immutable storage key already contains different bytes"
                        ) from None
                    continue
                if self._is_conditional_request_conflict(exc):
                    continue
                raise
            else:
                return StoredObject(
                    key=key,
                    content_type=content_type,
                    size_bytes=size_bytes,
                )

        raise StorageObjectConflictError(
            "Conditional storage publication did not settle"
        )

    def get_bytes(self, key: str) -> bytes:
        response = self.client.get_object(
            Bucket=self.bucket_name,
            Key=self._object_key(key),
        )
        body = response["Body"]
        return body.read()

    def exists(self, key: str) -> bool:
        try:
            self.client.head_object(
                Bucket=self.bucket_name,
                Key=self._object_key(key),
            )
        except ClientError as exc:
            code = str(exc.response.get("Error", {}).get("Code", ""))
            if code in {"404", "NoSuchKey", "NotFound"}:
                return False
            raise
        return True

    def delete(self, key: str) -> None:
        self.client.delete_object(Bucket=self.bucket_name, Key=self._object_key(key))

    def generate_download_url(self, key: str, expires_in_seconds: int) -> str:
        return self.client.generate_presigned_url(
            "get_object",
            Params={"Bucket": self.bucket_name, "Key": self._object_key(key)},
            ExpiresIn=expires_in_seconds,
        )

    def _object_key(self, key: str) -> str:
        safe_key = self._validate_key(key)
        if not self.key_prefix:
            return safe_key
        return f"{self.key_prefix}/{safe_key}"

    def _add_server_side_encryption(self, params: dict[str, Any]) -> None:
        if self.server_side_encryption is not None:
            params["ServerSideEncryption"] = self.server_side_encryption
        if self.sse_kms_key_id is not None:
            params["SSEKMSKeyId"] = self.sse_kms_key_id

    def _existing_file_matches(
        self,
        *,
        object_key: str,
        checksum_sha256: str,
        size_bytes: int,
    ) -> bool | None:
        try:
            response = self.client.head_object(
                Bucket=self.bucket_name,
                Key=object_key,
            )
        except ClientError as exc:
            if self._is_missing_object(exc):
                return None
            raise

        metadata = response.get("Metadata") or {}
        return (
            metadata.get("checksum-sha256") == checksum_sha256
            and response.get("ContentLength") == size_bytes
        )

    @staticmethod
    def _sha256_base64(checksum_sha256: str) -> str:
        try:
            digest = bytes.fromhex(checksum_sha256)
        except ValueError as exc:
            raise ValueError("Invalid SHA-256 checksum") from exc
        if len(digest) != 32:
            raise ValueError("Invalid SHA-256 checksum")
        return base64.b64encode(digest).decode("ascii")

    @staticmethod
    def _client_error_status(exc: ClientError) -> tuple[str, int]:
        code = str(exc.response.get("Error", {}).get("Code", ""))
        status = int(exc.response.get("ResponseMetadata", {}).get("HTTPStatusCode", 0))
        return code, status

    @classmethod
    def _is_precondition_failure(cls, exc: ClientError) -> bool:
        code, status = cls._client_error_status(exc)
        return status == 412 or code in {"412", "PreconditionFailed"}

    @classmethod
    def _is_conditional_request_conflict(cls, exc: ClientError) -> bool:
        code, status = cls._client_error_status(exc)
        return status == 409 or code in {"409", "ConditionalRequestConflict"}

    @classmethod
    def _is_missing_object(cls, exc: ClientError) -> bool:
        code, status = cls._client_error_status(exc)
        return status == 404 or code in {"404", "NoSuchKey", "NotFound"}

    @classmethod
    def _validate_key(cls, key: str) -> str:
        value = cls._normalise_required("storage key", key)
        if "\\" in value or ":" in value or "//" in value:
            raise ValueError("Invalid storage key")

        parsed = PurePosixPath(value)
        if (
            parsed.is_absolute()
            or not parsed.parts
            or any(part in {"", ".", ".."} for part in parsed.parts)
        ):
            raise ValueError("Invalid storage key")
        return "/".join(parsed.parts)

    @classmethod
    def _normalise_prefix(cls, value: str) -> str:
        candidate = cls._normalise_optional(value)
        if candidate is None:
            return ""
        return cls._validate_key(candidate.strip("/"))

    @staticmethod
    def _normalise_required(field_name: str, value: str | None) -> str:
        normalised = S3CompatibleStorageAdapter._normalise_optional(value)
        if normalised is None:
            raise ValueError(f"{field_name} is required")
        return normalised

    @staticmethod
    def _normalise_optional(value: str | None) -> str | None:
        if value is None:
            return None
        normalised = value.strip()
        return normalised or None

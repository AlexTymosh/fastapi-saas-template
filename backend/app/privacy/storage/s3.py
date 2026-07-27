from __future__ import annotations

import base64
from pathlib import Path, PurePosixPath
from typing import Any

import boto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError, HTTPClientError

from app.privacy.storage.base import (
    StorageObjectConflictError,
    StorageObjectState,
    StorageObjectStateUnknownError,
    StoragePublicationReservation,
    StoredObject,
)

_RESERVATION_OWNER_METADATA_KEY = "publication-reservation-owner"


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

    def reserve_file_publication(
        self,
        key: str,
        *,
        owner_token: str,
    ) -> StoragePublicationReservation:
        """Create a conditional marker that the archive PUT must replace."""

        object_key = self._object_key(key)
        params: dict[str, Any] = {
            "Bucket": self.bucket_name,
            "Key": object_key,
            "Body": b"",
            "ContentLength": 0,
            "ContentType": "application/octet-stream",
            "Metadata": {_RESERVATION_OWNER_METADATA_KEY: owner_token},
            "IfNoneMatch": "*",
        }
        self._add_server_side_encryption(params)

        for _ in range(self.max_conditional_write_attempts):
            try:
                response = self.client.put_object(**params)
            except ClientError as exc:
                if self._is_precondition_failure(exc):
                    existing = self._head_object(object_key)
                    if existing is None:
                        continue
                    metadata = existing.get("Metadata") or {}
                    revision = existing.get("ETag")
                    if metadata.get(
                        _RESERVATION_OWNER_METADATA_KEY
                    ) == owner_token and isinstance(revision, str):
                        return StoragePublicationReservation(
                            key=key,
                            owner_token=owner_token,
                            revision=revision,
                        )
                    raise StorageObjectConflictError(
                        "Storage key is reserved or published by another writer"
                    ) from None
                if self._is_conditional_request_conflict(exc):
                    continue
                raise
            revision = response.get("ETag")
            if not isinstance(revision, str):
                raise StorageObjectConflictError(
                    "Storage reservation response omitted its revision"
                )
            return StoragePublicationReservation(
                key=key,
                owner_token=owner_token,
                revision=revision,
            )

        raise StorageObjectConflictError(
            "Conditional storage reservation did not settle"
        )

    def publish_reserved_file(
        self,
        reservation: StoragePublicationReservation,
        path: Path,
        content_type: str,
        *,
        checksum_sha256: str,
    ) -> StoredObject:
        """Replace only the exact reservation observed before DB validation."""

        object_key = self._object_key(reservation.key)
        size_bytes = path.stat().st_size
        stored = StoredObject(
            key=reservation.key,
            content_type=content_type,
            size_bytes=size_bytes,
        )
        params: dict[str, Any] = {
            "Bucket": self.bucket_name,
            "Key": object_key,
            "ContentLength": size_bytes,
            "ContentType": content_type,
            "Metadata": {
                "privacy-artifact": "true",
                "checksum-sha256": checksum_sha256,
            },
            "IfMatch": reservation.revision,
            "ChecksumSHA256": self._sha256_base64(checksum_sha256),
        }
        self._add_server_side_encryption(params)
        try:
            with path.open("rb") as body:
                self.client.put_object(Body=body, **params)
        except ClientError as exc:
            if (
                self._is_precondition_failure(exc)
                or self._is_conditional_request_conflict(exc)
                or self._is_missing_object(exc)
            ):
                if self._published_object_matches(
                    reservation.key,
                    checksum_sha256=checksum_sha256,
                    size_bytes=size_bytes,
                ):
                    return stored
                raise StorageObjectConflictError(
                    "Storage publication reservation is no longer active"
                ) from None
            raise
        except HTTPClientError:
            if self._published_object_matches(
                reservation.key,
                checksum_sha256=checksum_sha256,
                size_bytes=size_bytes,
            ):
                return stored
            raise
        return stored

    def cancel_file_publication(
        self,
        reservation: StoragePublicationReservation,
    ) -> None:
        try:
            self.client.delete_object(
                Bucket=self.bucket_name,
                Key=self._object_key(reservation.key),
                IfMatch=reservation.revision,
            )
        except ClientError as exc:
            if (
                self._is_precondition_failure(exc)
                or self._is_conditional_request_conflict(exc)
                or self._is_missing_object(exc)
            ):
                return
            raise

    def inspect_file(
        self,
        key: str,
        *,
        checksum_sha256: str,
        size_bytes: int,
    ) -> StorageObjectState:
        response = self._head_object(self._object_key(key))
        return self._state_from_head_object(
            response,
            checksum_sha256=checksum_sha256,
            size_bytes=size_bytes,
        )

    @staticmethod
    def _state_from_head_object(
        response: dict[str, Any] | None,
        *,
        checksum_sha256: str,
        size_bytes: int,
    ) -> StorageObjectState:
        if response is None:
            return StorageObjectState.MISSING
        metadata = response.get("Metadata") or {}
        if metadata.get(_RESERVATION_OWNER_METADATA_KEY):
            return StorageObjectState.RESERVED
        if (
            metadata.get("checksum-sha256") == checksum_sha256
            and response.get("ContentLength") == size_bytes
        ):
            return StorageObjectState.MATCHING
        return StorageObjectState.CONFLICT

    def delete_file_if_not_matching(
        self,
        key: str,
        *,
        checksum_sha256: str,
        size_bytes: int,
    ) -> StorageObjectState:
        object_key = self._object_key(key)
        last_error: Exception | None = None
        for _ in range(self.max_conditional_write_attempts):
            existing = self._head_object(object_key)
            state = self._state_from_head_object(
                existing,
                checksum_sha256=checksum_sha256,
                size_bytes=size_bytes,
            )
            if state in {
                StorageObjectState.MISSING,
                StorageObjectState.MATCHING,
            }:
                return state

            revision = existing.get("ETag") if existing is not None else None
            if not isinstance(revision, str):
                raise StorageObjectConflictError(
                    "Stored object metadata omitted its revision"
                )
            try:
                self.client.delete_object(
                    Bucket=self.bucket_name,
                    Key=object_key,
                    IfMatch=revision,
                )
            except ClientError as exc:
                if self._is_missing_object(exc):
                    return StorageObjectState.MISSING
                if self._is_precondition_failure(
                    exc
                ) or self._is_conditional_request_conflict(exc):
                    last_error = None
                    continue
                last_error = exc
                continue
            except BotoCoreError as exc:
                last_error = exc
                continue
            return StorageObjectState.MISSING

        raise StorageObjectStateUnknownError(
            "Conditional storage deletion outcome could not be verified"
        ) from last_error

    def _published_object_matches(
        self,
        key: str,
        *,
        checksum_sha256: str,
        size_bytes: int,
    ) -> bool:
        return (
            self.inspect_file(
                key,
                checksum_sha256=checksum_sha256,
                size_bytes=size_bytes,
            )
            == StorageObjectState.MATCHING
        )

    def _head_object(self, object_key: str) -> dict[str, Any] | None:
        try:
            return self.client.head_object(
                Bucket=self.bucket_name,
                Key=object_key,
            )
        except ClientError as exc:
            if self._is_missing_object(exc):
                return None
            raise StorageObjectStateUnknownError(
                "Storage object state could not be inspected"
            ) from exc
        except BotoCoreError as exc:
            raise StorageObjectStateUnknownError(
                "Storage object state could not be inspected"
            ) from exc

    def get_bytes(self, key: str) -> bytes:
        response = self.client.get_object(
            Bucket=self.bucket_name,
            Key=self._object_key(key),
        )
        body = response["Body"]
        return body.read()

    def exists(self, key: str) -> bool:
        return self._head_object(self._object_key(key)) is not None

    def delete(self, key: str) -> None:
        object_key = self._object_key(key)
        for _ in range(self.max_conditional_write_attempts):
            existing = self._head_object(object_key)
            if existing is None:
                return
            revision = existing.get("ETag")
            if not isinstance(revision, str):
                raise StorageObjectConflictError(
                    "Stored object metadata omitted its revision"
                )
            try:
                self.client.delete_object(
                    Bucket=self.bucket_name,
                    Key=object_key,
                    IfMatch=revision,
                )
            except ClientError as exc:
                if self._is_missing_object(exc):
                    return
                if self._is_precondition_failure(
                    exc
                ) or self._is_conditional_request_conflict(exc):
                    continue
                raise
            return

        raise StorageObjectConflictError("Conditional storage deletion did not settle")

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

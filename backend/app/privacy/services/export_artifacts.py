from __future__ import annotations

import hashlib
import logging
import tempfile
import zipfile
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

from pydantic import SecretStr
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.context import AuditContext
from app.audit.models.audit_event import AuditAction, AuditCategory, AuditTargetType
from app.audit.services.audit_events import AuditEventService
from app.core.config.settings import get_settings
from app.core.errors import ConflictError, NotFoundError
from app.privacy.export_artifact_lifecycle import (
    clear_export_artifact_storage_metadata,
)
from app.privacy.exporters.base import ExportContext
from app.privacy.exporters.subject_data_stream import iter_subject_export_json_chunks
from app.privacy.models.data_subject_request import (
    DataSubjectRequest,
    DataSubjectRequestExecutionStatus,
    DataSubjectRequestStatus,
    DataSubjectRequestType,
)
from app.privacy.models.export_artifact import (
    ExportArtifact,
    ExportArtifactFormat,
    ExportArtifactStatus,
    ExportArtifactStorageBackend,
)
from app.privacy.repositories.data_subject_requests import DataSubjectRequestRepository
from app.privacy.repositories.export_artifacts import ExportArtifactRepository
from app.privacy.storage.base import StorageAdapter
from app.privacy.storage.local import LocalStorageAdapter
from app.privacy.storage.s3 import S3CompatibleStorageAdapter

DEFAULT_PROCESSING_LEASE_SECONDS = 3600
_EXPORT_ARCHIVE_READ_SIZE = 1024 * 1024
_DOWNLOAD_ELIGIBLE_DSR_STATUSES = frozenset(
    {
        DataSubjectRequestStatus.APPROVED.value,
        DataSubjectRequestStatus.FULFILLED.value,
    }
)
_EXPORT_GENERATION_FAILURE_CODES = frozenset(
    {
        "artifact_too_large",
        "dsr_not_found",
        "dsr_not_export_eligible",
    }
)
_SUBJECT_ERASURE_CANCELLED_EXPORT_REASON = "subject_erasure_requested"
_logger = logging.getLogger(__name__)


def _ensure_aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _optional_secret_value(secret: SecretStr | None) -> str | None:
    if secret is None:
        return None
    value = secret.get_secret_value().strip()
    return value or None


def _file_checksum_and_size(path: Path) -> tuple[str, int]:
    checksum = hashlib.sha256()
    size_bytes = 0
    with path.open("rb") as stream:
        while chunk := stream.read(_EXPORT_ARCHIVE_READ_SIZE):
            size_bytes += len(chunk)
            checksum.update(chunk)
    return checksum.hexdigest(), size_bytes


def _unlink_file(path: Path) -> None:
    try:
        path.unlink(missing_ok=True)
    except FileNotFoundError:
        return


@dataclass(frozen=True)
class ProcessingExportLease:
    artifact_id: UUID
    processing_token: str


@dataclass(frozen=True)
class PreparedExportArchive:
    artifact_id: UUID
    storage_backend: str
    storage_key: str
    filename: str
    content_type: str
    archive_path: Path
    size_bytes: int
    checksum_sha256: str


@dataclass(frozen=True)
class GeneratedExportDownloadUrl:
    url: str
    expires_in_seconds: int


class ExportArtifactService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repo = ExportArtifactRepository(session)
        self.dsr_repo = DataSubjectRequestRepository(session)
        self.audit = AuditEventService(session)
        self.settings = get_settings()
        self._storage_adapters: dict[str, StorageAdapter] = {}

    @property
    def storage(self) -> StorageAdapter:
        return self._storage_for_backend()

    def _storage_for_backend(self, backend: str | None = None) -> StorageAdapter:
        selected_backend = backend or self.settings.privacy_exports.storage_backend
        storage = self._storage_adapters.get(selected_backend)
        if storage is None:
            storage = self._build_storage(selected_backend)
            self._storage_adapters[selected_backend] = storage
        return storage

    def _build_storage(self, backend: str) -> StorageAdapter:
        exports = self.settings.privacy_exports

        if backend == ExportArtifactStorageBackend.LOCAL.value:
            return LocalStorageAdapter(
                exports.local_storage_path,
                exports.local_signing_secret,
            )

        if backend == ExportArtifactStorageBackend.S3_COMPATIBLE.value:
            return S3CompatibleStorageAdapter(
                bucket_name=exports.s3_bucket_name or "",
                region_name=exports.s3_region_name or "",
                endpoint_url=exports.s3_endpoint_url,
                access_key_id=_optional_secret_value(exports.s3_access_key_id),
                secret_access_key=_optional_secret_value(exports.s3_secret_access_key),
                key_prefix=exports.s3_key_prefix,
                server_side_encryption=exports.s3_server_side_encryption,
                sse_kms_key_id=exports.s3_sse_kms_key_id,
                addressing_style=exports.s3_addressing_style,
                connect_timeout_seconds=exports.s3_connect_timeout_seconds,
                read_timeout_seconds=exports.s3_read_timeout_seconds,
                max_attempts=exports.s3_max_attempts,
            )

        raise ValueError(f"Unsupported export artifact storage backend: {backend}")

    def _ensure_exports_enabled(self) -> None:
        if not self.settings.privacy_exports.enabled:
            raise ConflictError(detail="Privacy export artifacts are disabled")

    @staticmethod
    def _has_export_dsr_participant_links(dsr: DataSubjectRequest) -> bool:
        return dsr.subject_user_id is not None and dsr.requester_user_id is not None

    async def _ensure_download_dsr_is_still_eligible(
        self, artifact: ExportArtifact
    ) -> None:
        dsr = await self.dsr_repo.get_by_id(artifact.data_subject_request_id)
        if (
            dsr is None
            or not self._has_export_dsr_participant_links(dsr)
            or dsr.request_type != DataSubjectRequestType.EXPORT.value
            or dsr.status not in _DOWNLOAD_ELIGIBLE_DSR_STATUSES
        ):
            raise ConflictError(
                detail="Export artifact is no longer eligible for download"
            )

    async def _sync_export_dsr_execution_state(
        self,
        artifact: ExportArtifact,
        *,
        execution_status: DataSubjectRequestExecutionStatus,
        event_at: datetime | None = None,
        failure_reason_code: str | None = None,
        failure_detail: str | None = None,
    ) -> None:
        reference_now = _ensure_aware_utc(event_at or datetime.now(UTC))
        latest_artifact = await self._latest_export_artifact_for_dsr(
            artifact.data_subject_request_id
        )
        if latest_artifact is not None and latest_artifact.id != artifact.id:
            (
                execution_status,
                event_at,
                failure_reason_code,
                failure_detail,
            ) = await self._execution_state_for_dsr(latest_artifact, now=reference_now)
            artifact = latest_artifact
            reference_now = _ensure_aware_utc(event_at or reference_now)

        dsr = await self.dsr_repo.get_by_id(artifact.data_subject_request_id)
        if dsr is None or dsr.request_type != DataSubjectRequestType.EXPORT.value:
            return

        dsr.execution_status = execution_status.value

        if execution_status is DataSubjectRequestExecutionStatus.QUEUED:
            dsr.execution_started_at = None
            dsr.execution_completed_at = None
            dsr.execution_failed_at = None
            dsr.execution_failure_reason_code = None
            dsr.execution_failure_detail = None

        elif execution_status is DataSubjectRequestExecutionStatus.PROCESSING:
            if dsr.execution_started_at is None:
                dsr.execution_started_at = reference_now
            dsr.execution_completed_at = None
            dsr.execution_failed_at = None
            dsr.execution_failure_reason_code = None
            dsr.execution_failure_detail = None

        elif execution_status is DataSubjectRequestExecutionStatus.READY:
            dsr.execution_completed_at = reference_now
            dsr.execution_failed_at = None
            dsr.execution_failure_reason_code = None
            dsr.execution_failure_detail = None

        elif execution_status is DataSubjectRequestExecutionStatus.FAILED:
            dsr.execution_completed_at = None
            dsr.execution_failed_at = reference_now
            dsr.execution_failure_reason_code = failure_reason_code
            dsr.execution_failure_detail = failure_detail

        elif execution_status is DataSubjectRequestExecutionStatus.DELIVERED:
            if dsr.execution_completed_at is None:
                dsr.execution_completed_at = reference_now
            dsr.execution_failed_at = None
            dsr.execution_failure_reason_code = None
            dsr.execution_failure_detail = None

        await self.dsr_repo.save(dsr)

    async def _latest_export_artifact_for_dsr(
        self, data_subject_request_id: UUID
    ) -> ExportArtifact | None:
        artifacts = await self.repo.get_by_dsr_id(data_subject_request_id)
        latest_artifact: ExportArtifact | None = None
        latest_queued_at: datetime | None = None

        for candidate in artifacts:
            candidate_queued_at = _ensure_aware_utc(candidate.queued_at)
            if latest_queued_at is None or candidate_queued_at > latest_queued_at:
                latest_artifact = candidate
                latest_queued_at = candidate_queued_at

        return latest_artifact

    async def _execution_state_for_dsr(
        self,
        artifact: ExportArtifact,
        *,
        now: datetime,
    ) -> tuple[
        DataSubjectRequestExecutionStatus,
        datetime | None,
        str | None,
        str | None,
    ]:
        latest_artifact = await self._latest_export_artifact_for_dsr(
            artifact.data_subject_request_id
        )
        if latest_artifact is None:
            return DataSubjectRequestExecutionStatus.NOT_STARTED, now, None, None

        candidate = latest_artifact
        event_at: datetime | None

        if candidate.downloaded_at is not None or candidate.download_count > 0:
            event_at = candidate.downloaded_at or candidate.completed_at or now
            return (
                DataSubjectRequestExecutionStatus.DELIVERED,
                _ensure_aware_utc(event_at),
                None,
                None,
            )

        if candidate.status == ExportArtifactStatus.READY.value:
            expires_at = _ensure_aware_utc(candidate.expires_at)
            if expires_at > now:
                event_at = _ensure_aware_utc(candidate.completed_at or now)
                return DataSubjectRequestExecutionStatus.READY, event_at, None, None
            return (
                DataSubjectRequestExecutionStatus.FAILED,
                expires_at,
                "artifact_expired",
                "Export artifact expired before delivery",
            )

        if candidate.status == ExportArtifactStatus.PROCESSING.value:
            lease_expires_at = candidate.processing_lease_expires_at
            if lease_expires_at is not None:
                lease_expires_at = _ensure_aware_utc(lease_expires_at)
            if lease_expires_at is not None and lease_expires_at > now:
                event_at = _ensure_aware_utc(candidate.started_at or now)
                return (
                    DataSubjectRequestExecutionStatus.PROCESSING,
                    event_at,
                    None,
                    None,
                )
            event_at = _ensure_aware_utc(candidate.queued_at)
            return DataSubjectRequestExecutionStatus.QUEUED, event_at, None, None

        if candidate.status == ExportArtifactStatus.QUEUED.value:
            event_at = _ensure_aware_utc(candidate.queued_at)
            return DataSubjectRequestExecutionStatus.QUEUED, event_at, None, None

        if candidate.status == ExportArtifactStatus.EXPIRED.value:
            expires_at = _ensure_aware_utc(candidate.expires_at)
            return (
                DataSubjectRequestExecutionStatus.FAILED,
                expires_at,
                "artifact_expired",
                "Export artifact expired before delivery",
            )

        if candidate.status == ExportArtifactStatus.FAILED.value:
            event_at = candidate.failed_at or candidate.started_at or now
            return (
                DataSubjectRequestExecutionStatus.FAILED,
                _ensure_aware_utc(event_at),
                candidate.failure_reason_code,
                candidate.failure_detail,
            )

        return DataSubjectRequestExecutionStatus.NOT_STARTED, now, None, None

    async def request_export_artifact(
        self,
        *,
        request_id: UUID,
        requested_by_user_id: UUID,
        audit_context: AuditContext,
    ) -> ExportArtifact:
        self._ensure_exports_enabled()
        dsr = await self.dsr_repo.get_by_id(request_id)
        if dsr is None:
            raise NotFoundError(detail="Data subject request not found")
        if (
            dsr.request_type != DataSubjectRequestType.EXPORT.value
            or dsr.status != DataSubjectRequestStatus.APPROVED.value
            or not self._has_export_dsr_participant_links(dsr)
        ):
            raise ConflictError(
                detail=(
                    "Export artifact can only be requested for approved "
                    "export data-subject requests"
                )
            )

        queued_at = datetime.now(UTC)
        artifact = await self.repo.create(
            data_subject_request_id=dsr.id,
            subject_user_id=dsr.subject_user_id,
            requester_user_id=dsr.requester_user_id,
            status=ExportArtifactStatus.QUEUED.value,
            format=ExportArtifactFormat.JSON_ZIP.value,
            storage_backend=self.settings.privacy_exports.storage_backend,
            schema_version=self.settings.privacy_exports.schema_version,
            requested_by_user_id=requested_by_user_id,
            queued_at=queued_at,
            expires_at=queued_at
            + timedelta(days=self.settings.privacy_exports.artifact_retention_days),
        )
        await self._sync_export_dsr_execution_state(
            artifact,
            execution_status=DataSubjectRequestExecutionStatus.QUEUED,
            event_at=queued_at,
        )
        await self._record_event(
            audit_context, AuditAction.EXPORT_ARTIFACT_REQUESTED, artifact
        )
        return artifact

    async def get_own_export_artifact(
        self, *, artifact_id: UUID, requester_user_id: UUID
    ) -> ExportArtifact:
        artifact = await self.repo.get_by_id(artifact_id)
        if artifact is None or artifact.requester_user_id != requester_user_id:
            raise NotFoundError(detail="Export artifact not found")
        return artifact

    async def list_own_export_artifacts(
        self, *, requester_user_id: UUID, limit: int, offset: int
    ) -> tuple[list[ExportArtifact], int]:
        rows = await self.repo.list_for_requester(
            requester_user_id=requester_user_id, limit=limit, offset=offset
        )
        total = await self.repo.count_for_requester(requester_user_id=requester_user_id)
        return rows, total

    async def get_platform_export_artifact(
        self, *, artifact_id: UUID
    ) -> ExportArtifact:
        artifact = await self.repo.get_by_id(artifact_id)
        if artifact is None:
            raise NotFoundError(detail="Export artifact not found")
        return artifact

    async def list_platform_export_artifacts(
        self, *, limit: int, offset: int
    ) -> tuple[list[ExportArtifact], int]:
        rows = await self.repo.list_for_platform(limit=limit, offset=offset)
        total = await self.repo.count_for_platform()
        return rows, total

    async def generate_download_url(
        self, *, artifact: ExportArtifact, audit_context: AuditContext
    ) -> GeneratedExportDownloadUrl:
        self._ensure_exports_enabled()
        now = datetime.now(UTC)

        if artifact.status != ExportArtifactStatus.READY.value:
            raise ConflictError(detail="Export artifact is not available for download")

        await self._ensure_download_dsr_is_still_eligible(artifact)

        expires_at = _ensure_aware_utc(artifact.expires_at)
        remaining_seconds = int((expires_at - now).total_seconds())
        if remaining_seconds <= 0:
            raise ConflictError(detail="Export artifact is expired")

        if artifact.storage_key is None:
            raise ConflictError(detail="Export artifact is missing storage key")

        effective_ttl_seconds = min(
            self.settings.privacy_exports.download_url_ttl_seconds,
            remaining_seconds,
        )
        storage = self._storage_for_backend(artifact.storage_backend)
        url = storage.generate_download_url(artifact.storage_key, effective_ttl_seconds)
        issued_artifact = await self.repo.record_download_url_issued(artifact)
        await self._record_event(
            audit_context,
            AuditAction.EXPORT_ARTIFACT_DOWNLOAD_URL_CREATED,
            issued_artifact,
        )
        return GeneratedExportDownloadUrl(
            url=url, expires_in_seconds=effective_ttl_seconds
        )

    async def confirm_export_delivery(
        self, *, artifact: ExportArtifact, audit_context: AuditContext
    ) -> ExportArtifact:
        self._ensure_exports_enabled()
        now = datetime.now(UTC)

        if artifact.status != ExportArtifactStatus.READY.value:
            raise ConflictError(detail="Export artifact is not available for delivery")

        await self._ensure_download_dsr_is_still_eligible(artifact)

        expires_at = _ensure_aware_utc(artifact.expires_at)
        if expires_at <= now:
            raise ConflictError(
                detail="Export artifact delivery cannot be confirmed after expiry"
            )

        if artifact.storage_key is None:
            raise ConflictError(detail="Export artifact is missing storage key")

        delivered, newly_confirmed = await self.repo.confirm_delivery(
            artifact, delivered_at=now
        )
        if not newly_confirmed:
            if delivered.downloaded_at is None and delivered.download_count == 0:
                raise ConflictError(
                    detail="Export artifact is no longer available for delivery"
                )
            return delivered

        await self._sync_export_dsr_execution_state(
            delivered,
            execution_status=DataSubjectRequestExecutionStatus.DELIVERED,
            event_at=delivered.downloaded_at,
        )
        await self._record_event(
            audit_context,
            AuditAction.EXPORT_ARTIFACT_DELIVERY_CONFIRMED,
            delivered,
        )
        return delivered

    async def count_queued_artifacts(self, *, limit: int) -> int:
        if not self.settings.privacy_exports.enabled:
            return 0
        rows = await self.repo.peek_queued_batch(limit)
        return len(rows)

    async def claim_queued_artifact_leases(
        self, *, batch_size: int
    ) -> list[ProcessingExportLease]:
        if not self.settings.privacy_exports.enabled:
            return []
        await self.recover_stale_processing_artifacts(limit=batch_size)
        rows = await self.repo.claim_queued_batch(
            batch_size, lease_seconds=DEFAULT_PROCESSING_LEASE_SECONDS
        )
        for row in rows:
            await self._sync_export_dsr_execution_state(
                row,
                execution_status=DataSubjectRequestExecutionStatus.PROCESSING,
                event_at=row.started_at,
            )
        return [
            ProcessingExportLease(
                artifact_id=row.id,
                processing_token=row.processing_token,
            )
            for row in rows
            if row.processing_token is not None
        ]

    async def claim_queued_artifact_ids(self, *, batch_size: int) -> list[UUID]:
        leases = await self.claim_queued_artifact_leases(batch_size=batch_size)
        return [lease.artifact_id for lease in leases]

    async def renew_processing_lease(self, *, lease: ProcessingExportLease) -> bool:
        return await self.repo.renew_processing_lease(
            artifact_id=lease.artifact_id,
            processing_token=lease.processing_token,
            lease_seconds=DEFAULT_PROCESSING_LEASE_SECONDS,
        )

    async def recover_stale_processing_artifacts(self, *, limit: int) -> int:
        now = datetime.now(UTC)
        recovered = await self.repo.recover_stale_processing(now=now, limit=limit)
        for artifact in recovered:
            (
                execution_status,
                event_at,
                failure_reason_code,
                failure_detail,
            ) = await self._execution_state_for_dsr(artifact, now=now)
            await self._sync_export_dsr_execution_state(
                artifact,
                execution_status=execution_status,
                event_at=event_at,
                failure_reason_code=failure_reason_code,
                failure_detail=failure_detail,
            )
        return len(recovered)

    async def claim_and_generate_next_batch(
        self, *, batch_size: int, generated_by_user_id: UUID | None = None
    ) -> int:
        leases = await self.claim_queued_artifact_leases(batch_size=batch_size)
        for lease in leases:
            artifact = await self.repo.get_processing_by_token(
                artifact_id=lease.artifact_id,
                processing_token=lease.processing_token,
            )
            if artifact is not None:
                await self.generate_export_artifact(
                    artifact=artifact,
                    generated_by_user_id=generated_by_user_id,
                    processing_token=lease.processing_token,
                )
        return len(leases)

    async def generate_export_artifact(
        self,
        *,
        artifact: ExportArtifact,
        generated_by_user_id: UUID | None = None,
        processing_token: str | None = None,
    ) -> ExportArtifact:
        self._ensure_exports_enabled()
        token = processing_token or artifact.processing_token
        if token is None:
            token = str(uuid4())
            now = datetime.now(UTC)
            artifact.processing_token = token
            artifact.processing_lease_expires_at = now + timedelta(
                seconds=DEFAULT_PROCESSING_LEASE_SECONDS
            )
            if artifact.started_at is None:
                artifact.started_at = now
            artifact.status = ExportArtifactStatus.PROCESSING.value
            await self.repo.save(artifact)
            await self._sync_export_dsr_execution_state(
                artifact,
                execution_status=DataSubjectRequestExecutionStatus.PROCESSING,
                event_at=artifact.started_at,
            )

        try:
            prepared = await self.prepare_export_archive(
                artifact_id=artifact.id, processing_token=token
            )
            self.write_prepared_export_archive(prepared)
            return await self.mark_generated_export_artifact_ready(
                artifact_id=artifact.id,
                prepared=prepared,
                generated_by_user_id=generated_by_user_id,
                processing_token=token,
            )
        except Exception as exc:
            failed = await self.mark_export_artifact_failed(
                artifact_id=artifact.id,
                exc=exc,
                generated_by_user_id=generated_by_user_id,
                processing_token=token,
            )
            if failed is None:
                raise
            return failed

    async def prepare_export_archive(
        self, *, artifact_id: UUID, processing_token: str | None = None
    ) -> PreparedExportArchive:
        self._ensure_exports_enabled()
        if processing_token is None:
            artifact = await self.repo.get_by_id(artifact_id)
        else:
            artifact = await self.repo.get_processing_by_token(
                artifact_id=artifact_id, processing_token=processing_token
            )
        if artifact is None:
            raise NotFoundError(detail="Export artifact not found")
        if artifact.status != ExportArtifactStatus.PROCESSING.value:
            raise ConflictError(
                detail="Export artifact must be processing before generation"
            )

        dsr = await self.dsr_repo.get_by_id(artifact.data_subject_request_id)
        if dsr is None:
            raise ValueError("dsr_not_found")
        if (
            dsr.request_type != DataSubjectRequestType.EXPORT.value
            or dsr.status != DataSubjectRequestStatus.APPROVED.value
            or not self._has_export_dsr_participant_links(dsr)
        ):
            raise ValueError("dsr_not_export_eligible")

        now = datetime.now(UTC)
        archive_path = self._temporary_archive_path()
        try:
            await self._write_export_archive_file(
                archive_path,
                ExportContext(
                    artifact_id=artifact.id,
                    data_subject_request_id=dsr.id,
                    subject_user_id=dsr.subject_user_id,
                    requester_user_id=dsr.requester_user_id,
                    request_type=dsr.request_type,
                    request_status=dsr.status,
                    generated_at=now,
                    schema_version=artifact.schema_version,
                ),
            )
            checksum_sha256, size_bytes = _file_checksum_and_size(archive_path)
            if size_bytes > self.settings.privacy_exports.max_artifact_size_bytes:
                raise ValueError("artifact_too_large")

            storage_key = f"exports/{artifact.id}/{uuid4()}.zip"
            return PreparedExportArchive(
                artifact_id=artifact.id,
                storage_backend=artifact.storage_backend,
                storage_key=storage_key,
                filename=f"privacy-export-{artifact.id}.zip",
                content_type="application/zip",
                archive_path=archive_path,
                size_bytes=size_bytes,
                checksum_sha256=checksum_sha256,
            )
        except Exception:
            _unlink_file(archive_path)
            raise

    def _temporary_archive_path(self) -> Path:
        temporary_dir = Path(self.settings.privacy_exports.local_storage_path).resolve()
        temporary_dir.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            dir=temporary_dir,
            prefix="privacy-export-",
            suffix=".tmp",
            delete=False,
        ) as temporary_file:
            return Path(temporary_file.name)

    async def _write_export_archive_file(
        self,
        archive_path: Path,
        context: ExportContext,
    ) -> None:
        with archive_path.open("wb") as archive_stream:
            with zipfile.ZipFile(
                archive_stream,
                mode="w",
                compression=zipfile.ZIP_DEFLATED,
                allowZip64=True,
            ) as archive:
                with archive.open(
                    "export.json",
                    mode="w",
                    force_zip64=True,
                ) as json_stream:
                    async for chunk in iter_subject_export_json_chunks(
                        self.session,
                        context,
                    ):
                        json_stream.write(chunk.encode("utf-8"))

    def write_prepared_export_archive(self, prepared: PreparedExportArchive) -> None:
        storage = self._storage_for_backend(prepared.storage_backend)
        try:
            storage.put_file(
                prepared.storage_key,
                prepared.archive_path,
                prepared.content_type,
            )
        finally:
            _unlink_file(prepared.archive_path)

    async def mark_generated_export_artifact_ready(
        self,
        *,
        artifact_id: UUID,
        prepared: PreparedExportArchive,
        generated_by_user_id: UUID | None = None,
        processing_token: str | None = None,
    ) -> ExportArtifact:
        if processing_token is None:
            artifact = await self.repo.get_by_id(artifact_id)
        else:
            artifact = await self.repo.get_processing_by_token(
                artifact_id=artifact_id,
                processing_token=processing_token,
            )
        if artifact is None:
            raise ConflictError(
                detail="Export artifact processing lease is no longer active"
            )
        artifact.storage_key = prepared.storage_key
        artifact.filename = prepared.filename
        artifact.content_type = prepared.content_type
        artifact.size_bytes = prepared.size_bytes
        artifact.checksum_sha256 = prepared.checksum_sha256
        artifact.generated_by_user_id = generated_by_user_id
        ready = await self.repo.mark_ready(artifact)
        await self._sync_export_dsr_execution_state(
            ready,
            execution_status=DataSubjectRequestExecutionStatus.READY,
            event_at=ready.completed_at,
        )
        await self._record_event(
            AuditContext(actor_user_id=generated_by_user_id),
            AuditAction.EXPORT_ARTIFACT_GENERATED,
            ready,
        )
        return ready

    async def mark_export_artifact_failed(
        self,
        *,
        artifact_id: UUID,
        exc: Exception,
        generated_by_user_id: UUID | None = None,
        processing_token: str | None = None,
    ) -> ExportArtifact | None:
        if processing_token is None:
            artifact = await self.repo.get_by_id(artifact_id)
        else:
            artifact = await self.repo.get_processing_by_token(
                artifact_id=artifact_id,
                processing_token=processing_token,
            )
        if artifact is None:
            return None
        code = (
            str(exc)
            if str(exc) in _EXPORT_GENERATION_FAILURE_CODES
            else "generation_failed"
        )
        failed = await self.repo.mark_failed(
            artifact, reason_code=code, detail="Export generation failed"
        )
        await self._sync_export_dsr_execution_state(
            failed,
            execution_status=DataSubjectRequestExecutionStatus.FAILED,
            event_at=failed.failed_at,
            failure_reason_code=code,
            failure_detail=failed.failure_detail,
        )
        await self._record_event(
            AuditContext(actor_user_id=generated_by_user_id),
            AuditAction.EXPORT_ARTIFACT_FAILED,
            failed,
        )
        return failed

    async def count_expired_ready_artifacts(
        self, *, now: datetime | None = None, limit: int = 1000
    ) -> int:
        self._validate_positive_limit(limit)
        now_value = _ensure_aware_utc(now or datetime.now(UTC))

        expired_ready = await self.repo.list_expired_ready(
            now=now_value,
            limit=limit,
        )
        remaining_limit = limit - len(expired_ready)
        if remaining_limit <= 0:
            return len(expired_ready)

        cancelled_erasure = await self.repo.list_cancelled_erasure_purge_retry(
            limit=remaining_limit,
        )
        remaining_limit -= len(cancelled_erasure)
        if remaining_limit <= 0:
            return len(expired_ready) + len(cancelled_erasure)

        expired_storage_retry = await self.repo.list_expired_storage_purge_retry(
            limit=remaining_limit,
        )
        return len(expired_ready) + len(cancelled_erasure) + len(expired_storage_retry)

    async def mark_expired_artifacts(
        self, *, now: datetime | None = None, limit: int = 1000
    ) -> int:
        self._validate_positive_limit(limit)
        now_value = _ensure_aware_utc(now or datetime.now(UTC))

        cancelled_erasure = await self.repo.list_cancelled_erasure_purge_retry(
            limit=limit,
        )
        expired_storage_retry = await self.repo.list_expired_storage_purge_retry(
            limit=limit,
        )

        expired_ready = await self.repo.list_expired_ready(
            now=now_value,
            limit=limit,
        )
        processed = 0
        for artifact in expired_ready:
            expired_artifact = await self.repo.mark_expired(artifact)
            processed += 1
            (
                execution_status,
                event_at,
                failure_reason_code,
                failure_detail,
            ) = await self._execution_state_for_dsr(expired_artifact, now=now_value)
            await self._sync_export_dsr_execution_state(
                expired_artifact,
                execution_status=execution_status,
                event_at=event_at,
                failure_reason_code=failure_reason_code,
                failure_detail=failure_detail,
            )
            await self._record_event(
                AuditContext(actor_user_id=None),
                AuditAction.EXPORT_ARTIFACT_EXPIRED,
                expired_artifact,
            )

        remaining_limit = limit - processed
        if remaining_limit <= 0:
            return processed

        processed += await self._purge_storage_retry_artifacts(
            cancelled_erasure,
            limit=remaining_limit,
        )
        remaining_limit = limit - processed
        if remaining_limit <= 0:
            return processed

        processed += await self._purge_storage_retry_artifacts(
            expired_storage_retry,
            limit=remaining_limit,
        )
        return processed

    async def _purge_storage_retry_artifacts(
        self, artifacts: list[ExportArtifact], *, limit: int
    ) -> int:
        processed = 0
        for artifact in artifacts[:limit]:
            if not self._try_purge_export_artifact_storage_object(artifact):
                continue
            await self.repo.save(artifact)
            processed += 1
        return processed

    def _try_purge_export_artifact_storage_object(
        self, artifact: ExportArtifact
    ) -> bool:
        if artifact.storage_key is None:
            return True
        if not _is_non_downloadable_storage_purge_retry(artifact):
            raise ConflictError(
                detail="Export artifact storage purge requires non-downloadable state"
            )

        try:
            self._purge_export_artifact_storage_object(artifact)
        except Exception:
            _logger.exception(
                "Failed to purge export artifact storage object",
                extra={
                    "artifact_id": str(artifact.id),
                    "storage_backend": artifact.storage_backend,
                },
            )
            return False
        return True

    @staticmethod
    def _validate_positive_limit(limit: int) -> None:
        if limit < 1:
            raise ValueError("Export artifact retention limit must be positive")

    def _purge_export_artifact_storage_object(self, artifact: ExportArtifact) -> None:
        storage_key = artifact.storage_key
        if storage_key is None:
            return
        if not _is_non_downloadable_storage_purge_retry(artifact):
            raise ConflictError(
                detail="Export artifact storage purge requires non-downloadable state"
            )

        storage = self._storage_for_backend(artifact.storage_backend)
        storage.delete(storage_key)
        clear_export_artifact_storage_metadata(artifact)

    async def _record_event(
        self, audit_context: AuditContext, action: AuditAction, artifact: ExportArtifact
    ) -> None:
        await self.audit.record_event(
            audit_context=audit_context,
            category=AuditCategory.COMPLIANCE,
            action=action,
            target_type=AuditTargetType.EXPORT_ARTIFACT,
            target_id=artifact.id,
            metadata_json={"status": artifact.status, "format": artifact.format},
        )


def _is_non_downloadable_storage_purge_retry(artifact: ExportArtifact) -> bool:
    if artifact.status == ExportArtifactStatus.EXPIRED.value:
        return True
    return (
        artifact.status == ExportArtifactStatus.CANCELLED.value
        and artifact.failure_reason_code == _SUBJECT_ERASURE_CANCELLED_EXPORT_REASON
    )

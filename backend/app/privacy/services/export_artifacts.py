from __future__ import annotations

import hashlib
import io
import json
import zipfile
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.context import AuditContext
from app.audit.models.audit_event import AuditAction, AuditCategory, AuditTargetType
from app.audit.services.audit_events import AuditEventService
from app.core.config.settings import get_settings
from app.core.errors import ConflictError, NotFoundError
from app.privacy.exporters.base import ExportContext
from app.privacy.exporters.minimal import MinimalSubjectDataExporter
from app.privacy.models.data_subject_request import (
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
from app.privacy.storage.local import LocalStorageAdapter

DEFAULT_PROCESSING_LEASE_SECONDS = 3600


def _ensure_aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


@dataclass(frozen=True)
class ProcessingExportLease:
    artifact_id: UUID
    processing_token: str


@dataclass(frozen=True)
class PreparedExportArchive:
    artifact_id: UUID
    storage_key: str
    filename: str
    content_type: str
    archive_bytes: bytes
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
        self.storage = self._build_storage()

    def _build_storage(self) -> LocalStorageAdapter:
        backend = self.settings.privacy_exports.storage_backend
        if backend == ExportArtifactStorageBackend.LOCAL.value:
            return LocalStorageAdapter(
                self.settings.privacy_exports.local_storage_path,
                self.settings.privacy_exports.local_signing_secret,
            )
        raise NotImplementedError("s3_compatible storage is not implemented")

    def _ensure_exports_enabled(self) -> None:
        if not self.settings.privacy_exports.enabled:
            raise ConflictError(detail="Privacy export artifacts are disabled")

    async def _ensure_download_dsr_is_still_eligible(
        self, artifact: ExportArtifact
    ) -> None:
        dsr = await self.dsr_repo.get_by_id(artifact.data_subject_request_id)
        if (
            dsr is None
            or dsr.request_type != DataSubjectRequestType.EXPORT.value
            or dsr.status != DataSubjectRequestStatus.APPROVED.value
        ):
            raise ConflictError(
                detail="Export artifact is no longer eligible for download"
            )

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
        ):
            raise ConflictError(
                detail=(
                    "Export artifact can only be requested for approved "
                    "export data-subject requests"
                )
            )

        artifact = await self.repo.create(
            data_subject_request_id=dsr.id,
            subject_user_id=dsr.subject_user_id,
            requester_user_id=dsr.requester_user_id,
            status=ExportArtifactStatus.QUEUED.value,
            format=ExportArtifactFormat.JSON_ZIP.value,
            storage_backend=ExportArtifactStorageBackend.LOCAL.value,
            schema_version=self.settings.privacy_exports.schema_version,
            requested_by_user_id=requested_by_user_id,
            queued_at=datetime.now(UTC),
            expires_at=datetime.now(UTC)
            + timedelta(days=self.settings.privacy_exports.artifact_retention_days),
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
        url = self.storage.generate_download_url(
            artifact.storage_key, effective_ttl_seconds
        )
        await self.repo.increment_download_count(artifact)
        await self._record_event(
            audit_context, AuditAction.EXPORT_ARTIFACT_DOWNLOAD_URL_CREATED, artifact
        )
        return GeneratedExportDownloadUrl(
            url=url, expires_in_seconds=effective_ttl_seconds
        )

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
        return [
            ProcessingExportLease(
                artifact_id=row.id, processing_token=row.processing_token
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
            artifact.processing_token = token
            artifact.processing_lease_expires_at = datetime.now(UTC) + timedelta(
                seconds=DEFAULT_PROCESSING_LEASE_SECONDS
            )
            if artifact.started_at is None:
                artifact.started_at = datetime.now(UTC)
            await self.repo.save(artifact)

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
        ):
            raise ValueError("dsr_not_export_eligible")

        now = datetime.now(UTC)
        payload = MinimalSubjectDataExporter().export_subject_data(
            ExportContext(
                artifact_id=artifact.id,
                data_subject_request_id=dsr.id,
                subject_user_id=dsr.subject_user_id,
                requester_user_id=dsr.requester_user_id,
                request_type=dsr.request_type,
                request_status=dsr.status,
                generated_at=now,
                schema_version=artifact.schema_version,
            )
        )
        with io.BytesIO() as stream:
            with zipfile.ZipFile(
                stream, mode="w", compression=zipfile.ZIP_DEFLATED
            ) as archive:
                archive.writestr(
                    "export.json",
                    json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
                )
            archive_bytes = stream.getvalue()

        if len(archive_bytes) > self.settings.privacy_exports.max_artifact_size_bytes:
            raise ValueError("artifact_too_large")

        storage_key = f"exports/{artifact.id}/{uuid4()}.zip"
        return PreparedExportArchive(
            artifact_id=artifact.id,
            storage_key=storage_key,
            filename=f"privacy-export-{artifact.id}.zip",
            content_type="application/zip",
            archive_bytes=archive_bytes,
            size_bytes=len(archive_bytes),
            checksum_sha256=hashlib.sha256(archive_bytes).hexdigest(),
        )

    def write_prepared_export_archive(self, prepared: PreparedExportArchive) -> None:
        self.storage.put_bytes(
            prepared.storage_key, prepared.archive_bytes, prepared.content_type
        )

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
                artifact_id=artifact_id, processing_token=processing_token
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
                artifact_id=artifact_id, processing_token=processing_token
            )
        if artifact is None:
            return None
        code = (
            str(exc)
            if str(exc)
            in {"artifact_too_large", "dsr_not_found", "dsr_not_export_eligible"}
            else "generation_failed"
        )
        failed = await self.repo.mark_failed(
            artifact, reason_code=code, detail="Export generation failed"
        )
        await self._record_event(
            AuditContext(actor_user_id=generated_by_user_id),
            AuditAction.EXPORT_ARTIFACT_FAILED,
            failed,
        )
        return failed

    async def mark_expired_artifacts(self, *, now: datetime | None = None) -> int:
        now_value = _ensure_aware_utc(now or datetime.now(UTC))
        candidates = await self.repo.list_expired_ready(now=now_value, limit=1000)
        expired = 0
        for artifact in candidates:
            await self.repo.mark_expired(artifact)
            expired += 1
            await self._record_event(
                AuditContext(actor_user_id=None),
                AuditAction.EXPORT_ARTIFACT_EXPIRED,
                artifact,
            )
        return expired

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

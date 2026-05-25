from __future__ import annotations

import hashlib
import io
import json
import zipfile
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

    async def request_export_artifact(
        self,
        *,
        request_id: UUID,
        requested_by_user_id: UUID,
        audit_context: AuditContext,
    ) -> ExportArtifact:
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
    ) -> str:
        if artifact.status != ExportArtifactStatus.READY.value:
            raise ConflictError(detail="Export artifact is not available for download")
        if artifact.expires_at <= datetime.now(UTC):
            raise ConflictError(detail="Export artifact is expired")
        if artifact.storage_key is None:
            raise ConflictError(detail="Export artifact is missing storage key")
        url = self.storage.generate_download_url(
            artifact.storage_key, self.settings.privacy_exports.download_url_ttl_seconds
        )
        await self.repo.increment_download_count(artifact)
        await self._record_event(
            audit_context, AuditAction.EXPORT_ARTIFACT_DOWNLOAD_URL_CREATED, artifact
        )
        return url

    async def claim_and_generate_next_batch(
        self, *, batch_size: int, generated_by_user_id: UUID | None = None
    ) -> int:
        rows = await self.repo.claim_queued_batch(batch_size)
        for row in rows:
            await self.generate_export_artifact(
                artifact=row, generated_by_user_id=generated_by_user_id
            )
        return len(rows)

    async def generate_export_artifact(
        self, *, artifact: ExportArtifact, generated_by_user_id: UUID | None = None
    ) -> ExportArtifact:
        try:
            dsr = await self.dsr_repo.get_by_id(artifact.data_subject_request_id)
            if dsr is None:
                raise ValueError("dsr_not_found")
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
            if (
                len(archive_bytes)
                > self.settings.privacy_exports.max_artifact_size_bytes
            ):
                raise ValueError("artifact_too_large")

            storage_key = f"exports/{artifact.id}/{uuid4()}.zip"
            self.storage.put_bytes(storage_key, archive_bytes, "application/zip")
            artifact.storage_key = storage_key
            artifact.filename = f"privacy-export-{artifact.id}.zip"
            artifact.content_type = "application/zip"
            artifact.size_bytes = len(archive_bytes)
            artifact.checksum_sha256 = hashlib.sha256(archive_bytes).hexdigest()
            artifact.generated_by_user_id = generated_by_user_id
            ready = await self.repo.mark_ready(artifact)
            await self._record_event(
                AuditContext(actor_user_id=generated_by_user_id),
                AuditAction.EXPORT_ARTIFACT_GENERATED,
                ready,
            )
            return ready
        except Exception as exc:
            code = (
                str(exc)
                if str(exc) in {"artifact_too_large", "dsr_not_found"}
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
        now_value = now or datetime.now(UTC)
        candidates = await self.repo.list_for_platform(limit=1000, offset=0)
        expired = 0
        for artifact in candidates:
            if (
                artifact.status == ExportArtifactStatus.READY.value
                and artifact.expires_at <= now_value
            ):
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

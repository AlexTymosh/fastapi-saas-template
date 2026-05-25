from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.context import AuditContext
from app.audit.models.audit_event import AuditAction, AuditCategory, AuditTargetType
from app.audit.services.audit_events import AuditEventService
from app.core.config import get_settings
from app.core.errors import ConflictError, NotFoundError
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
        self.storage = LocalStorageAdapter(
            self.settings.privacy_exports.local_storage_path
        )

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
                    "Export artifact can only be requested for "
                    "approved export data-subject requests"
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
            expires_at=(
                datetime.now(UTC)
                + timedelta(days=self.settings.privacy_exports.artifact_retention_days)
            ),
        )
        await self.audit.record_event(
            audit_context=audit_context,
            category=AuditCategory.COMPLIANCE,
            action=AuditAction.EXPORT_ARTIFACT_REQUESTED,
            target_type=AuditTargetType.EXPORT_ARTIFACT,
            target_id=artifact.id,
            metadata_json={"status": artifact.status, "format": artifact.format},
        )
        return artifact

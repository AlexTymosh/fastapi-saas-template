from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.privacy.export_artifact_lifecycle import (
    mark_export_artifact_expired,
    mark_export_artifact_failed,
    mark_export_artifact_ready,
)
from app.privacy.models.export_artifact import ExportArtifact, ExportArtifactStatus


class ExportArtifactRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    def _supports_skip_locked(self) -> bool:
        return (
            self.session.bind is not None and self.session.bind.dialect.name != "sqlite"
        )

    async def create(self, **kwargs) -> ExportArtifact:
        row = ExportArtifact(**kwargs)
        self.session.add(row)
        await self.session.flush()
        await self.session.refresh(row)
        return row

    async def get_by_id(self, artifact_id: UUID) -> ExportArtifact | None:
        return (
            await self.session.execute(
                select(ExportArtifact).where(ExportArtifact.id == artifact_id)
            )
        ).scalar_one_or_none()

    async def get_by_dsr_id(self, request_id: UUID) -> list[ExportArtifact]:
        stmt = (
            select(ExportArtifact)
            .where(ExportArtifact.data_subject_request_id == request_id)
            .order_by(ExportArtifact.created_at.desc())
        )
        return list((await self.session.execute(stmt)).scalars().all())

    async def list_for_requester(
        self, *, requester_user_id: UUID, limit: int, offset: int
    ) -> list[ExportArtifact]:
        stmt = (
            select(ExportArtifact)
            .where(ExportArtifact.requester_user_id == requester_user_id)
            .order_by(ExportArtifact.created_at.desc())
            .offset(offset)
            .limit(limit)
        )
        return list((await self.session.execute(stmt)).scalars().all())

    async def list_for_platform(
        self, *, limit: int, offset: int
    ) -> list[ExportArtifact]:
        stmt = (
            select(ExportArtifact)
            .order_by(ExportArtifact.created_at.desc())
            .offset(offset)
            .limit(limit)
        )
        return list((await self.session.execute(stmt)).scalars().all())

    async def count_for_requester(self, *, requester_user_id: UUID) -> int:
        stmt = (
            select(func.count())
            .select_from(ExportArtifact)
            .where(ExportArtifact.requester_user_id == requester_user_id)
        )
        return int((await self.session.execute(stmt)).scalar_one())

    async def count_for_platform(self) -> int:
        stmt = select(func.count()).select_from(ExportArtifact)
        return int((await self.session.execute(stmt)).scalar_one())

    async def peek_queued_batch(self, limit: int) -> list[ExportArtifact]:
        stmt = (
            select(ExportArtifact)
            .where(ExportArtifact.status == ExportArtifactStatus.QUEUED.value)
            .order_by(ExportArtifact.queued_at.asc())
            .limit(limit)
        )
        return list((await self.session.execute(stmt)).scalars().all())

    async def claim_queued_batch(
        self, limit: int, *, lease_seconds: int
    ) -> list[ExportArtifact]:
        stmt = (
            select(ExportArtifact)
            .where(ExportArtifact.status == ExportArtifactStatus.QUEUED.value)
            .order_by(ExportArtifact.queued_at.asc())
            .limit(limit)
        )
        if self._supports_skip_locked():
            stmt = stmt.with_for_update(skip_locked=True)
        rows = list((await self.session.execute(stmt)).scalars().all())
        now = datetime.now(UTC)
        lease_expires_at = now + timedelta(seconds=lease_seconds)
        for row in rows:
            row.status = ExportArtifactStatus.PROCESSING.value
            row.started_at = now
            row.processing_token = str(uuid4())
            row.processing_lease_expires_at = lease_expires_at
        await self.session.flush()
        return rows

    async def renew_processing_lease(
        self, *, artifact_id: UUID, processing_token: str, lease_seconds: int
    ) -> bool:
        artifact = await self.get_processing_by_token(
            artifact_id=artifact_id, processing_token=processing_token
        )
        if artifact is None:
            return False
        artifact.processing_lease_expires_at = datetime.now(UTC) + timedelta(
            seconds=lease_seconds
        )
        await self.session.flush()
        return True

    async def get_processing_by_token(
        self, *, artifact_id: UUID, processing_token: str
    ) -> ExportArtifact | None:
        stmt = select(ExportArtifact).where(
            ExportArtifact.id == artifact_id,
            ExportArtifact.status == ExportArtifactStatus.PROCESSING.value,
            ExportArtifact.processing_token == processing_token,
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def recover_stale_processing(
        self, *, now: datetime, limit: int
    ) -> list[ExportArtifact]:
        stmt = (
            select(ExportArtifact)
            .where(
                ExportArtifact.status == ExportArtifactStatus.PROCESSING.value,
                ExportArtifact.processing_lease_expires_at.is_not(None),
                ExportArtifact.processing_lease_expires_at < now,
            )
            .order_by(ExportArtifact.processing_lease_expires_at.asc())
            .limit(limit)
        )
        if self._supports_skip_locked():
            stmt = stmt.with_for_update(skip_locked=True)
        stale = list((await self.session.execute(stmt)).scalars().all())
        for artifact in stale:
            artifact.status = ExportArtifactStatus.QUEUED.value
            artifact.started_at = None
            artifact.processing_token = None
            artifact.processing_lease_expires_at = None
        await self.session.flush()
        return stale

    async def list_expired_ready(
        self, *, now: datetime, limit: int
    ) -> list[ExportArtifact]:
        stmt = (
            select(ExportArtifact)
            .where(
                ExportArtifact.status == ExportArtifactStatus.READY.value,
                ExportArtifact.expires_at <= now,
            )
            .order_by(ExportArtifact.expires_at.asc())
            .limit(limit)
        )
        return list((await self.session.execute(stmt)).scalars().all())

    async def list_cancelled_erasure_purge_retry(
        self, *, limit: int
    ) -> list[ExportArtifact]:
        stmt = (
            select(ExportArtifact)
            .where(
                ExportArtifact.status == ExportArtifactStatus.CANCELLED.value,
                ExportArtifact.failure_reason_code == "subject_erasure_requested",
                ExportArtifact.storage_key.is_not(None),
            )
            .order_by(
                ExportArtifact.completed_at.asc().nulls_last(),
                ExportArtifact.created_at.asc(),
                ExportArtifact.id.asc(),
            )
            .limit(limit)
        )
        return list((await self.session.execute(stmt)).scalars().all())

    async def mark_ready(self, artifact: ExportArtifact) -> ExportArtifact:
        mark_export_artifact_ready(artifact)
        await self.session.flush()
        await self.session.refresh(artifact)
        return artifact

    async def mark_failed(
        self, artifact: ExportArtifact, *, reason_code: str, detail: str
    ) -> ExportArtifact:
        mark_export_artifact_failed(
            artifact,
            reason_code=reason_code,
            detail=detail,
        )
        await self.session.flush()
        await self.session.refresh(artifact)
        return artifact

    async def mark_expired(self, artifact: ExportArtifact) -> ExportArtifact:
        mark_export_artifact_expired(artifact)
        await self.session.flush()
        await self.session.refresh(artifact)
        return artifact

    async def record_download_url_issued(
        self, artifact: ExportArtifact
    ) -> ExportArtifact:
        await self.session.execute(
            update(ExportArtifact)
            .where(ExportArtifact.id == artifact.id)
            .values(
                download_url_issue_count=(ExportArtifact.download_url_issue_count + 1),
                download_url_issued_at=datetime.now(UTC),
            )
        )
        await self.session.flush()
        await self.session.refresh(artifact)
        return artifact

    async def confirm_delivery(
        self, artifact: ExportArtifact, *, delivered_at: datetime | None = None
    ) -> ExportArtifact:
        reference_time = delivered_at or datetime.now(UTC)
        if artifact.downloaded_at is not None or artifact.download_count > 0:
            await self.session.refresh(artifact)
            return artifact

        await self.session.execute(
            update(ExportArtifact)
            .where(ExportArtifact.id == artifact.id)
            .values(
                download_count=ExportArtifact.download_count + 1,
                downloaded_at=reference_time,
            )
        )
        await self.session.flush()
        await self.session.refresh(artifact)
        return artifact

    async def increment_download_count(
        self, artifact: ExportArtifact
    ) -> ExportArtifact:
        return await self.confirm_delivery(artifact)

    async def save(self, artifact: ExportArtifact) -> ExportArtifact:
        self.session.add(artifact)
        await self.session.flush()
        await self.session.refresh(artifact)
        return artifact

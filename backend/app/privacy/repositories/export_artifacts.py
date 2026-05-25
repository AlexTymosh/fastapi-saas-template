from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.privacy.models.export_artifact import ExportArtifact, ExportArtifactStatus


class ExportArtifactRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

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

    async def claim_queued_batch(self, limit: int) -> list[ExportArtifact]:
        stmt = (
            select(ExportArtifact)
            .where(ExportArtifact.status == ExportArtifactStatus.QUEUED.value)
            .order_by(ExportArtifact.queued_at.asc())
            .limit(limit)
        )
        if self.session.bind is not None and self.session.bind.dialect.name != "sqlite":
            stmt = stmt.with_for_update(skip_locked=True)
        rows = list((await self.session.execute(stmt)).scalars().all())
        now = datetime.now(UTC)
        for row in rows:
            row.status = ExportArtifactStatus.PROCESSING.value
            row.started_at = now
        await self.session.flush()
        return rows

    async def mark_ready(self, artifact: ExportArtifact) -> ExportArtifact:
        artifact.status = ExportArtifactStatus.READY.value
        artifact.completed_at = datetime.now(UTC)
        await self.session.flush()
        await self.session.refresh(artifact)
        return artifact

    async def mark_failed(
        self, artifact: ExportArtifact, *, reason_code: str, detail: str
    ) -> ExportArtifact:
        artifact.status = ExportArtifactStatus.FAILED.value
        artifact.failure_reason_code = reason_code
        artifact.failure_detail = detail[:255]
        artifact.failed_at = datetime.now(UTC)
        await self.session.flush()
        await self.session.refresh(artifact)
        return artifact

    async def mark_expired(self, artifact: ExportArtifact) -> ExportArtifact:
        artifact.status = ExportArtifactStatus.EXPIRED.value
        await self.session.flush()
        await self.session.refresh(artifact)
        return artifact

    async def increment_download_count(
        self, artifact: ExportArtifact
    ) -> ExportArtifact:
        artifact.download_count += 1
        artifact.downloaded_at = datetime.now(UTC)
        await self.session.flush()
        await self.session.refresh(artifact)
        return artifact

    async def save(self, artifact: ExportArtifact) -> ExportArtifact:
        self.session.add(artifact)
        await self.session.flush()
        await self.session.refresh(artifact)
        return artifact

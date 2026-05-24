from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.privacy.models.data_subject_request import DataSubjectRequest


class DataSubjectRequestRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(self, **kwargs) -> DataSubjectRequest:
        request = DataSubjectRequest(**kwargs)
        self.session.add(request)
        await self.session.flush()
        await self.session.refresh(request)
        return request

    async def get_by_id(self, request_id: UUID) -> DataSubjectRequest | None:
        stmt = select(DataSubjectRequest).where(DataSubjectRequest.id == request_id)
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def get_by_id_for_requester(
        self,
        *,
        request_id: UUID,
        requester_user_id: UUID,
    ) -> DataSubjectRequest | None:
        stmt = select(DataSubjectRequest).where(
            DataSubjectRequest.id == request_id,
            DataSubjectRequest.requester_user_id == requester_user_id,
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def get_by_id_for_subject(
        self,
        *,
        request_id: UUID,
        subject_user_id: UUID,
    ) -> DataSubjectRequest | None:
        stmt = select(DataSubjectRequest).where(
            DataSubjectRequest.id == request_id,
            DataSubjectRequest.subject_user_id == subject_user_id,
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def get_non_expired_by_idempotency_key_hash(
        self,
        *,
        requester_user_id: UUID,
        idempotency_key_hash: str,
        now: datetime,
    ) -> DataSubjectRequest | None:
        stmt = (
            select(DataSubjectRequest)
            .where(
                DataSubjectRequest.requester_user_id == requester_user_id,
                DataSubjectRequest.idempotency_key_hash == idempotency_key_hash,
                DataSubjectRequest.idempotency_key_expires_at.is_not(None),
                DataSubjectRequest.idempotency_key_expires_at > now,
            )
            .order_by(DataSubjectRequest.created_at.desc())
            .limit(1)
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def save(self, request: DataSubjectRequest) -> DataSubjectRequest:
        self.session.add(request)
        await self.session.flush()
        await self.session.refresh(request)
        return request

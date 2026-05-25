from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.privacy.models.data_subject_request import DataSubjectRequest
from app.users.models.user import User


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

    async def lock_requester_for_idempotency(
        self,
        *,
        requester_user_id: UUID,
    ) -> None:
        """Serialize idempotent submit checks for one requester.

        This deliberately locks the existing requester row instead of adding a
        permanent uniqueness constraint to the DSR table. PostgreSQL renders
        ``key_share=True`` as ``FOR NO KEY UPDATE``, which is strong enough to
        serialize same-requester idempotency checks but weaker than ``FOR UPDATE``
        and does not block foreign-key ``FOR KEY SHARE`` checks that only need
        to verify the requester row still exists.
        """
        stmt = (
            select(User.id)
            .where(User.id == requester_user_id)
            .with_for_update(key_share=True)
        )
        await self.session.execute(stmt)

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

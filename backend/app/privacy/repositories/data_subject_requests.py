from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import func, select, update
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

    async def get_by_id(
        self, request_id: UUID, *, populate_existing: bool = False
    ) -> DataSubjectRequest | None:
        stmt = select(DataSubjectRequest).where(DataSubjectRequest.id == request_id)
        if populate_existing:
            stmt = stmt.execution_options(populate_existing=True)
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

    async def transition_status_if_current(
        self,
        *,
        request_id: UUID,
        expected_status: str,
        values: Mapping[str, Any],
    ) -> DataSubjectRequest | None:
        """Atomically update one DSR only if its status has not changed."""
        stmt = (
            update(DataSubjectRequest)
            .where(
                DataSubjectRequest.id == request_id,
                DataSubjectRequest.status == expected_status,
            )
            .values(**values)
            .returning(DataSubjectRequest)
            .execution_options(synchronize_session="fetch")
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def save(self, request: DataSubjectRequest) -> DataSubjectRequest:
        self.session.add(request)
        await self.session.flush()
        await self.session.refresh(request)
        return request

    async def list_for_requester(
        self,
        *,
        requester_user_id: UUID,
        limit: int,
        offset: int,
        status: str | None = None,
        request_type: str | None = None,
    ) -> list[DataSubjectRequest]:
        stmt = select(DataSubjectRequest).where(
            DataSubjectRequest.requester_user_id == requester_user_id
        )
        if status is not None:
            stmt = stmt.where(DataSubjectRequest.status == status)
        if request_type is not None:
            stmt = stmt.where(DataSubjectRequest.request_type == request_type)
        stmt = (
            stmt.order_by(DataSubjectRequest.created_at.desc())
            .offset(offset)
            .limit(limit)
        )
        return list((await self.session.execute(stmt)).scalars().all())

    async def count_for_requester(
        self,
        *,
        requester_user_id: UUID,
        status: str | None = None,
        request_type: str | None = None,
    ) -> int:
        stmt = (
            select(func.count())
            .select_from(DataSubjectRequest)
            .where(DataSubjectRequest.requester_user_id == requester_user_id)
        )
        if status is not None:
            stmt = stmt.where(DataSubjectRequest.status == status)
        if request_type is not None:
            stmt = stmt.where(DataSubjectRequest.request_type == request_type)
        return int((await self.session.execute(stmt)).scalar_one())

    async def list_for_platform(
        self,
        *,
        limit: int,
        offset: int,
        status: str | None = None,
        request_type: str | None = None,
        subject_user_id: UUID | None = None,
        requester_user_id: UUID | None = None,
        due_before: datetime | None = None,
        due_after: datetime | None = None,
    ) -> list[DataSubjectRequest]:
        stmt = select(DataSubjectRequest)
        if status is not None:
            stmt = stmt.where(DataSubjectRequest.status == status)
        if request_type is not None:
            stmt = stmt.where(DataSubjectRequest.request_type == request_type)
        if subject_user_id is not None:
            stmt = stmt.where(DataSubjectRequest.subject_user_id == subject_user_id)
        if requester_user_id is not None:
            stmt = stmt.where(DataSubjectRequest.requester_user_id == requester_user_id)
        if due_before is not None:
            stmt = stmt.where(DataSubjectRequest.due_at <= due_before)
        if due_after is not None:
            stmt = stmt.where(DataSubjectRequest.due_at >= due_after)
        stmt = (
            stmt.order_by(DataSubjectRequest.created_at.desc())
            .offset(offset)
            .limit(limit)
        )
        return list((await self.session.execute(stmt)).scalars().all())

    async def count_for_platform(
        self,
        *,
        status: str | None = None,
        request_type: str | None = None,
        subject_user_id: UUID | None = None,
        requester_user_id: UUID | None = None,
        due_before: datetime | None = None,
        due_after: datetime | None = None,
    ) -> int:
        stmt = select(func.count()).select_from(DataSubjectRequest)
        if status is not None:
            stmt = stmt.where(DataSubjectRequest.status == status)
        if request_type is not None:
            stmt = stmt.where(DataSubjectRequest.request_type == request_type)
        if subject_user_id is not None:
            stmt = stmt.where(DataSubjectRequest.subject_user_id == subject_user_id)
        if requester_user_id is not None:
            stmt = stmt.where(DataSubjectRequest.requester_user_id == requester_user_id)
        if due_before is not None:
            stmt = stmt.where(DataSubjectRequest.due_at <= due_before)
        if due_after is not None:
            stmt = stmt.where(DataSubjectRequest.due_at >= due_after)
        return int((await self.session.execute(stmt)).scalar_one())

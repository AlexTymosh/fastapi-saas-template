from __future__ import annotations
from datetime import datetime
from uuid import UUID
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.privacy.models.data_subject_request import DataSubjectRequest
class DataSubjectRequestRepository:
    def __init__(self, session: AsyncSession) -> None: self.session=session
    async def create(self, **kwargs) -> DataSubjectRequest:
        obj=DataSubjectRequest(**kwargs); self.session.add(obj); await self.session.flush(); await self.session.refresh(obj); return obj
    async def get_by_id(self, request_id: UUID): return (await self.session.execute(select(DataSubjectRequest).where(DataSubjectRequest.id==request_id))).scalar_one_or_none()
    async def get_by_id_for_requester(self, request_id: UUID, requester_user_id: UUID): return (await self.session.execute(select(DataSubjectRequest).where(DataSubjectRequest.id==request_id,DataSubjectRequest.requester_user_id==requester_user_id))).scalar_one_or_none()
    async def get_by_id_for_subject(self, request_id: UUID, subject_user_id: UUID): return (await self.session.execute(select(DataSubjectRequest).where(DataSubjectRequest.id==request_id,DataSubjectRequest.subject_user_id==subject_user_id))).scalar_one_or_none()
    async def get_non_expired_by_idempotency_key_hash(self, requester_user_id: UUID, key_hash: str, now: datetime): return (await self.session.execute(select(DataSubjectRequest).where(DataSubjectRequest.requester_user_id==requester_user_id,DataSubjectRequest.idempotency_key_hash==key_hash,DataSubjectRequest.idempotency_key_expires_at.is_not(None),DataSubjectRequest.idempotency_key_expires_at>now).order_by(DataSubjectRequest.created_at.desc()))).scalars().first()
    async def list_for_requester(self, requester_user_id: UUID, limit:int, offset:int):
        rows=(await self.session.execute(select(DataSubjectRequest).where(DataSubjectRequest.requester_user_id==requester_user_id).order_by(DataSubjectRequest.created_at.desc()).limit(limit).offset(offset))).scalars().all(); return list(rows)
    async def list_for_subject(self, subject_user_id: UUID, limit:int, offset:int): return list((await self.session.execute(select(DataSubjectRequest).where(DataSubjectRequest.subject_user_id==subject_user_id).order_by(DataSubjectRequest.created_at.desc()).limit(limit).offset(offset))).scalars().all())
    async def list_for_platform(self, limit:int, offset:int): return list((await self.session.execute(select(DataSubjectRequest).order_by(DataSubjectRequest.created_at.desc()).limit(limit).offset(offset))).scalars().all())
    async def update_status_fields(self, request: DataSubjectRequest, **kwargs):
        for k,v in kwargs.items(): setattr(request,k,v)
        await self.session.flush(); await self.session.refresh(request); return request
    async def save(self, request: DataSubjectRequest): self.session.add(request); await self.session.flush(); await self.session.refresh(request); return request

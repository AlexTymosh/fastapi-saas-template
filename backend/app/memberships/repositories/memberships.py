from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.memberships.models.membership import Membership, MembershipRole


class MembershipRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create_membership(
        self,
        *,
        user_id: UUID,
        organisation_id: UUID,
        role: MembershipRole,
    ) -> Membership:
        membership = Membership(
            user_id=user_id,
            organisation_id=organisation_id,
            role=role,
        )
        self.session.add(membership)
        await self.session.flush()
        return membership

    async def list_memberships_for_organisation(
        self,
        *,
        organisation_id: UUID,
    ) -> list[Membership]:
        stmt = select(Membership).where(Membership.organisation_id == organisation_id)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def list_memberships_for_user(self, *, user_id: UUID) -> list[Membership]:
        stmt = select(Membership).where(Membership.user_id == user_id)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def has_membership(
        self,
        *,
        user_id: UUID,
        organisation_id: UUID,
    ) -> bool:
        stmt = (
            select(Membership.id)
            .where(Membership.user_id == user_id)
            .where(Membership.organisation_id == organisation_id)
            .limit(1)
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none() is not None

    async def get_membership(
        self,
        *,
        user_id: UUID,
        organisation_id: UUID,
    ) -> Membership | None:
        stmt = (
            select(Membership)
            .where(Membership.user_id == user_id)
            .where(Membership.organisation_id == organisation_id)
            .limit(1)
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

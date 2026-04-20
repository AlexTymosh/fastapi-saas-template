from __future__ import annotations

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.memberships.models.membership import Membership, MembershipRole
from app.repositories.memberships import MembershipRepository


class MembershipService:
    def __init__(self, session: AsyncSession) -> None:
        self.membership_repository = MembershipRepository(session)

    async def create_membership(
        self,
        *,
        user_id: UUID,
        organisation_id: UUID,
        role: MembershipRole,
    ) -> Membership:
        return await self.membership_repository.create_membership(
            user_id=user_id,
            organisation_id=organisation_id,
            role=role,
        )

    async def list_memberships_for_organisation(
        self,
        organisation_id: UUID,
    ) -> list[Membership]:
        return await self.membership_repository.list_memberships_for_organisation(
            organisation_id=organisation_id,
        )

    async def list_memberships_for_user(self, user_id: UUID) -> list[Membership]:
        return await self.membership_repository.list_memberships_for_user(
            user_id=user_id,
        )

from __future__ import annotations

from uuid import UUID

from app.memberships.models.membership import Membership, MembershipRole
from app.memberships.repositories.membership_repository import MembershipRepository


class MembershipService:
    def __init__(self, membership_repository: MembershipRepository) -> None:
        self.membership_repository = membership_repository

    async def create_owner_membership(
        self,
        *,
        user_id: UUID,
        organisation_id: UUID,
    ) -> Membership:
        return await self.membership_repository.create_membership(
            user_id=user_id,
            organisation_id=organisation_id,
            role=MembershipRole.OWNER,
        )

    async def list_memberships_for_organisation(
        self,
        organisation_id: UUID,
    ) -> list[Membership]:
        return await self.membership_repository.list_memberships_for_organisation(
            organisation_id
        )

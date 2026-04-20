from __future__ import annotations

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.memberships.services.memberships import MembershipService
from app.organisations.models.organisation import Organisation
from app.organisations.services.organisations import OrganisationService


class OrganisationAccessService:
    def __init__(self, session: AsyncSession) -> None:
        self.organisation_service = OrganisationService(session)
        self.membership_service = MembershipService(session)

    async def get_member_organisation(
        self,
        *,
        organisation_id: UUID,
        user_id: UUID,
    ) -> Organisation:
        organisation = await self.organisation_service.get_organisation(organisation_id)
        await self.membership_service.ensure_user_has_membership(
            user_id=user_id,
            organisation_id=organisation_id,
        )
        return organisation

    async def ensure_member_access(
        self,
        *,
        organisation_id: UUID,
        user_id: UUID,
    ) -> None:
        await self.organisation_service.get_organisation(organisation_id)
        await self.membership_service.ensure_user_has_membership(
            user_id=user_id,
            organisation_id=organisation_id,
        )

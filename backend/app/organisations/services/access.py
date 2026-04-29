from __future__ import annotations

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.access_control.guards import ensure_organisation_active
from app.core.auth import AuthenticatedPrincipal
from app.memberships.models.membership import Membership
from app.memberships.services.memberships import MembershipService
from app.organisations.models.organisation import Organisation
from app.organisations.services.organisations import OrganisationService
from app.users.services.users import UserService


class OrganisationAccessService:
    def __init__(self, session: AsyncSession) -> None:
        self.user_service = UserService(session)
        self.organisation_service = OrganisationService(session)
        self.membership_service = MembershipService(session)

    async def get_organisation_for_member(
        self,
        *,
        identity: AuthenticatedPrincipal,
        organisation_id: UUID,
    ) -> Organisation:
        user = await self.user_service.provision_current_user(identity=identity)
        await self.user_service.ensure_user_is_active(user)
        organisation = await self.organisation_service.get_organisation(
            organisation_id=organisation_id
        )
        ensure_organisation_active(organisation)
        await self.membership_service.ensure_user_has_organisation_access(
            user_id=user.id,
            organisation_id=organisation_id,
        )
        return organisation

    async def list_memberships_for_member_organisation(
        self,
        *,
        identity: AuthenticatedPrincipal,
        organisation_id: UUID,
    ) -> list[Membership]:
        organisation = await self.organisation_service.get_organisation(
            organisation_id=organisation_id
        )
        ensure_organisation_active(organisation)

        user = await self.user_service.provision_current_user(identity=identity)
        await self.user_service.ensure_user_is_active(user)
        await self.membership_service.ensure_user_can_list_organisation_memberships(
            user_id=user.id,
            organisation_id=organisation_id,
        )

        return await self.membership_service.list_memberships_for_organisation(
            organisation_id=organisation_id,
            actor_user_id=user.id,
        )

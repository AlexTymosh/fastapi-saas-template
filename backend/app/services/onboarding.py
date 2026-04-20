from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import AuthenticatedIdentity
from app.memberships.models.membership import Membership, MembershipRole
from app.organisations.models.organisation import Organisation
from app.services.memberships import MembershipService
from app.services.organisations import OrganisationService
from app.services.users import UserService
from app.users.models.user import User


class OnboardingService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.user_service = UserService(session)
        self.organisation_service = OrganisationService(session)
        self.membership_service = MembershipService(session)

    async def create_organisation_for_current_user(
        self,
        *,
        identity: AuthenticatedIdentity,
        organisation_name: str,
        organisation_slug: str,
    ) -> tuple[User, Organisation, Membership]:
        async with self.session.begin():
            user = await self.user_service.get_or_create_current_user(identity)
            organisation = await self.organisation_service.create_organisation(
                name=organisation_name,
                slug=organisation_slug,
            )
            membership = await self.membership_service.create_membership(
                user_id=user.id,
                organisation_id=organisation.id,
                role=MembershipRole.OWNER,
            )
            if not user.onboarding_completed:
                await self.user_service.user_repository.update_onboarding_completed(
                    user,
                    onboarding_completed=True,
                )

        return user, organisation, membership

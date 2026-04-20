from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import AuthenticatedIdentity
from app.memberships.services.membership_service import MembershipService
from app.organisations.models.organisation import Organisation
from app.organisations.services.organisation_service import OrganisationService
from app.users.services.user_service import UserService


class OnboardingService:
    def __init__(
        self,
        session: AsyncSession,
        user_service: UserService,
        organisation_service: OrganisationService,
        membership_service: MembershipService,
    ) -> None:
        self.session = session
        self.user_service = user_service
        self.organisation_service = organisation_service
        self.membership_service = membership_service

    async def create_organisation_for_current_user(
        self,
        *,
        identity: AuthenticatedIdentity,
        name: str,
        slug: str,
    ) -> Organisation:
        async with self.session.begin():
            user = await self.user_service.get_or_create_current_user(identity)
            organisation = await self.organisation_service.create(name=name, slug=slug)
            await self.membership_service.create_owner_membership(
                user_id=user.id,
                organisation_id=organisation.id,
            )
            if not user.onboarding_completed:
                await self.user_service.user_repository.update_profile_fields(
                    user,
                    email=user.email,
                    email_verified=user.email_verified,
                    first_name=user.first_name,
                    last_name=user.last_name,
                    onboarding_completed=True,
                )

        return organisation

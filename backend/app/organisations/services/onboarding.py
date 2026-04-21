from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import AuthenticatedPrincipal
from app.core.errors.exceptions import ConflictError
from app.memberships.models.membership import Membership, MembershipRole
from app.memberships.services.memberships import MembershipService
from app.organisations.models.organisation import Organisation
from app.organisations.services.organisations import OrganisationService
from app.users.models.user import User
from app.users.services.users import UserService


class OnboardingService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.user_service = UserService(session)
        self.organisation_service = OrganisationService(session)
        self.membership_service = MembershipService(session)

    async def create_organisation_for_current_user(
        self,
        *,
        identity: AuthenticatedPrincipal,
        organisation_name: str,
        organisation_slug: str,
    ) -> tuple[User, Organisation, Membership]:
        async with self.session.begin():
            user = await self.user_service.get_or_create_current_user(identity)
            existing_memberships = (
                await self.membership_service.list_memberships_for_user(user.id)
            )
            if existing_memberships:
                raise ConflictError(
                    detail=(
                        "You already belong to an organisation and cannot create "
                        "another"
                    ),
                )
            organisation = await self.organisation_service.create_organisation(
                name=organisation_name,
                slug=organisation_slug,
            )
            membership = await self.membership_service.create_membership(
                user_id=user.id,
                organisation_id=organisation.id,
                role=MembershipRole.OWNER,
            )
            user = await self.user_service.mark_onboarding_completed(user)

        return user, organisation, membership

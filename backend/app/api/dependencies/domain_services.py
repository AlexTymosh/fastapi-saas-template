from __future__ import annotations

from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db_session
from app.memberships.repositories.membership_repository import MembershipRepository
from app.memberships.services.membership_service import MembershipService
from app.onboarding.services.onboarding_service import OnboardingService
from app.organisations.repositories.organisation_repository import (
    OrganisationRepository,
)
from app.organisations.services.organisation_service import OrganisationService
from app.users.repositories.user_repository import UserRepository
from app.users.services.user_service import UserService

DbSession = Annotated[AsyncSession, Depends(get_db_session)]


async def get_user_service(session: DbSession) -> UserService:
    return UserService(
        user_repository=UserRepository(session),
        membership_repository=MembershipRepository(session),
    )


async def get_organisation_service(session: DbSession) -> OrganisationService:
    return OrganisationService(organisation_repository=OrganisationRepository(session))


async def get_membership_service(session: DbSession) -> MembershipService:
    return MembershipService(membership_repository=MembershipRepository(session))


async def get_onboarding_service(session: DbSession) -> OnboardingService:
    user_repository = UserRepository(session)
    membership_repository = MembershipRepository(session)

    return OnboardingService(
        session=session,
        user_service=UserService(
            user_repository=user_repository,
            membership_repository=membership_repository,
        ),
        organisation_service=OrganisationService(
            organisation_repository=OrganisationRepository(session)
        ),
        membership_service=MembershipService(
            membership_repository=membership_repository
        ),
    )

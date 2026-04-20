from __future__ import annotations

from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors.exceptions import ForbiddenError
from app.core.errors.integrity import raise_conflict_for_integrity_error
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
        try:
            return await self.membership_repository.create_membership(
                user_id=user_id,
                organisation_id=organisation_id,
                role=role,
            )
        except IntegrityError as exc:
            raise_conflict_for_integrity_error(exc)

    async def ensure_user_has_membership(
        self,
        *,
        user_id: UUID,
        organisation_id: UUID,
    ) -> None:
        membership = await self.membership_repository.get_membership_for_user(
            user_id=user_id,
            organisation_id=organisation_id,
        )
        if membership is None:
            raise ForbiddenError(detail="Access to organisation is denied")

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

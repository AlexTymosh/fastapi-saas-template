from __future__ import annotations

from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors.exceptions import ConflictError, ForbiddenError
from app.memberships.models.membership import Membership, MembershipRole
from app.memberships.repositories.memberships import MembershipRepository


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
        existing_membership = await self.membership_repository.get_membership_for_user(
            user_id=user_id
        )
        if existing_membership is not None:
            raise ConflictError(detail="User already belongs to an organisation")

        try:
            return await self.membership_repository.create_membership(
                user_id=user_id,
                organisation_id=organisation_id,
                role=role,
            )
        except IntegrityError as exc:
            raise ConflictError(
                detail="User already belongs to an organisation"
            ) from exc

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

    async def get_membership_for_user(self, user_id: UUID) -> Membership | None:
        return await self.membership_repository.get_membership_for_user(user_id=user_id)

    async def ensure_user_has_organisation_access(
        self,
        *,
        user_id: UUID,
        organisation_id: UUID,
    ) -> None:
        has_membership = await self.membership_repository.has_membership(
            user_id=user_id,
            organisation_id=organisation_id,
        )
        if not has_membership:
            raise ForbiddenError(
                detail="You are not a member of this organisation",
            )

    async def ensure_user_can_list_organisation_memberships(
        self,
        *,
        user_id: UUID,
        organisation_id: UUID,
    ) -> None:
        membership = await self.membership_repository.get_membership(
            user_id=user_id,
            organisation_id=organisation_id,
        )
        if membership is None or membership.role not in {
            MembershipRole.OWNER,
            MembershipRole.ADMIN,
        }:
            raise ForbiddenError(
                detail="You are not allowed to view organisation memberships",
            )

    async def ensure_user_can_create_organisation(self, *, user_id: UUID) -> None:
        has_membership = await self.membership_repository.has_any_membership_for_user(
            user_id=user_id
        )
        if has_membership:
            raise ConflictError(
                detail="You already belong to an organisation",
            )

from __future__ import annotations

from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import AuthenticatedPrincipal
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

    async def transfer_user_membership(
        self,
        *,
        user_id: UUID,
        organisation_id: UUID,
        role: MembershipRole,
    ) -> Membership:
        existing = await self.membership_repository.get_membership_for_user(user_id=user_id)
        if existing is not None:
            if existing.role == MembershipRole.OWNER:
                owner_count = await self.membership_repository.count_active_owners(
                    organisation_id=existing.organisation_id
                )
                if owner_count <= 1:
                    raise ForbiddenError(detail="Organisation must always have at least one owner")
            await self.membership_repository.deactivate_membership(existing)

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
        membership = await self.membership_repository.get_membership_for_user(
            user_id=user_id
        )
        if membership is not None:
            raise ConflictError(
                detail="You already belong to an organisation",
            )

    async def ensure_user_can_invite(
        self,
        *,
        identity: AuthenticatedPrincipal,
        user_id: UUID,
        organisation_id: UUID,
        role_to_assign: MembershipRole,
    ) -> None:
        if identity.is_superadmin():
            return

        membership = await self.membership_repository.get_membership(
            user_id=user_id,
            organisation_id=organisation_id,
        )
        if membership is None:
            raise ForbiddenError(detail="You are not allowed to invite users")
        if membership.role not in {MembershipRole.OWNER, MembershipRole.ADMIN}:
            raise ForbiddenError(detail="You are not allowed to invite users")
        if membership.role == MembershipRole.ADMIN and role_to_assign == MembershipRole.ADMIN:
            raise ForbiddenError(detail="Admins cannot assign admin role")

    async def ensure_can_remove_member(
        self,
        *,
        actor_user_id: UUID,
        organisation_id: UUID,
        target_membership: Membership,
    ) -> None:
        actor = await self.membership_repository.get_membership(
            user_id=actor_user_id,
            organisation_id=organisation_id,
        )
        if actor is None or actor.role not in {MembershipRole.OWNER, MembershipRole.ADMIN}:
            raise ForbiddenError(detail="You are not allowed to remove users")
        if target_membership.role == MembershipRole.OWNER:
            raise ForbiddenError(detail="Owner cannot be removed")

    async def leave_organisation(self, *, membership: Membership) -> None:
        if membership.role == MembershipRole.OWNER:
            owner_count = await self.membership_repository.count_active_owners(
                organisation_id=membership.organisation_id
            )
            if owner_count <= 1:
                raise ForbiddenError(detail="Owner cannot leave organisation without another owner")
        await self.membership_repository.deactivate_membership(membership)

from __future__ import annotations

from uuid import UUID

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.memberships.models.membership import Membership, MembershipRole
from app.users.models.user import User


class MembershipRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create_membership(
        self,
        *,
        user_id: UUID,
        organisation_id: UUID,
        role: MembershipRole,
    ) -> Membership:
        membership = Membership(
            user_id=user_id,
            organisation_id=organisation_id,
            role=role,
            is_active=True,
        )
        self.session.add(membership)
        await self.session.flush()
        return membership

    async def list_memberships_for_organisation(
        self,
        *,
        organisation_id: UUID,
    ) -> list[Membership]:
        stmt = (
            select(Membership)
            .where(
                Membership.organisation_id == organisation_id,
                Membership.is_active.is_(True),
            )
            .options(selectinload(Membership.user))
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def list_directory_members_for_organisation(
        self,
        *,
        organisation_id: UUID,
    ) -> list[tuple[str | None, str | None]]:
        stmt = (
            select(User.first_name, User.last_name)
            .join(Membership, Membership.user_id == User.id)
            .where(
                Membership.organisation_id == organisation_id,
                Membership.is_active.is_(True),
            )
        )
        result = await self.session.execute(stmt)
        return list(result.all())

    async def get_membership_for_user(self, *, user_id: UUID) -> Membership | None:
        stmt = (
            select(Membership)
            .where(Membership.user_id == user_id, Membership.is_active.is_(True))
            .options(selectinload(Membership.organisation))
            .limit(1)
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def has_membership(
        self,
        *,
        user_id: UUID,
        organisation_id: UUID,
    ) -> bool:
        stmt = (
            select(Membership.id)
            .where(
                Membership.user_id == user_id,
                Membership.organisation_id == organisation_id,
                Membership.is_active.is_(True),
            )
            .limit(1)
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none() is not None

    async def get_membership(
        self,
        *,
        user_id: UUID,
        organisation_id: UUID,
    ) -> Membership | None:
        stmt = (
            select(Membership)
            .where(
                Membership.user_id == user_id,
                Membership.organisation_id == organisation_id,
                Membership.is_active.is_(True),
            )
            .limit(1)
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_membership_by_id(
        self,
        *,
        membership_id: UUID,
        organisation_id: UUID,
    ) -> Membership | None:
        stmt = (
            select(Membership)
            .where(
                Membership.id == membership_id,
                Membership.organisation_id == organisation_id,
                Membership.is_active.is_(True),
            )
            .limit(1)
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def has_any_membership_for_user(self, *, user_id: UUID) -> bool:
        return await self.get_membership_for_user(user_id=user_id) is not None

    async def update_role(
        self,
        membership: Membership,
        *,
        role: MembershipRole,
    ) -> Membership:
        membership.role = role
        await self.session.flush()
        return membership

    async def deactivate_membership(self, membership: Membership) -> Membership:
        membership.is_active = False
        await self.session.flush()
        return membership

    async def count_active_owners(self, *, organisation_id: UUID) -> int:
        stmt = select(func.count(Membership.id)).where(
            Membership.organisation_id == organisation_id,
            Membership.role == MembershipRole.OWNER,
            Membership.is_active.is_(True),
        )
        result = await self.session.execute(stmt)
        return int(result.scalar_one())

    async def deactivate_organisation_memberships(
        self,
        *,
        organisation_id: UUID,
    ) -> None:
        stmt = (
            update(Membership)
            .where(
                Membership.organisation_id == organisation_id,
                Membership.is_active.is_(True),
            )
            .values(is_active=False)
        )
        await self.session.execute(stmt)

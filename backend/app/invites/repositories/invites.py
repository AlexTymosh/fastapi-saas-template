from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.invites.models.invite import Invite, InviteStatus
from app.memberships.models.membership import MembershipRole


class InviteRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(
        self,
        *,
        email: str,
        organisation_id: UUID,
        role: MembershipRole,
        token: str,
    ) -> Invite:
        invite = Invite(
            email=email,
            organisation_id=organisation_id,
            role=role,
            token=token,
            status=InviteStatus.PENDING,
        )
        self.session.add(invite)
        await self.session.flush()
        return invite

    async def get_by_token(self, *, token: str) -> Invite | None:
        stmt = select(Invite).where(Invite.token == token).limit(1)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def mark_accepted(self, invite: Invite) -> Invite:
        invite.status = InviteStatus.ACCEPTED
        await self.session.flush()
        return invite

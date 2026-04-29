from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.invites.models.invite import Invite, InviteStatus
from app.memberships.models.membership import MembershipRole


class InviteRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create_invite(
        self,
        *,
        email: str,
        organisation_id: UUID,
        role: MembershipRole,
        token_hash: str,
        expires_at: datetime | None,
    ) -> Invite:
        invite = Invite(
            email=email,
            organisation_id=organisation_id,
            role=role,
            token_hash=token_hash,
            expires_at=expires_at,
        )
        self.session.add(invite)
        await self.session.flush()
        await self.session.refresh(invite)
        return invite

    async def get_by_token_hash(self, token_hash: str) -> Invite | None:
        stmt = select(Invite).where(Invite.token_hash == token_hash).limit(1)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_pending_invite_by_email(
        self, *, organisation_id: UUID, email: str
    ) -> Invite | None:
        stmt = (
            select(Invite)
            .where(
                Invite.organisation_id == organisation_id,
                func.lower(Invite.email) == email.lower(),
                Invite.status == InviteStatus.PENDING,
            )
            .limit(1)
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_invite_for_organisation(
        self, *, invite_id: UUID, organisation_id: UUID
    ) -> Invite | None:
        stmt = (
            select(Invite)
            .where(Invite.id == invite_id, Invite.organisation_id == organisation_id)
            .limit(1)
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def mark_revoked(self, invite: Invite, *, revoked_by_user_id: UUID) -> Invite:
        invite.status = InviteStatus.REVOKED
        invite.revoked_at = datetime.now(UTC)
        invite.revoked_by_user_id = revoked_by_user_id
        await self.session.flush()
        await self.session.refresh(invite)
        return invite

    async def mark_status(self, invite: Invite, status: InviteStatus) -> Invite:
        invite.status = status
        await self.session.flush()
        await self.session.refresh(invite)
        return invite

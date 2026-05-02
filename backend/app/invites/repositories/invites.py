from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import func, select, update
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

    async def accept_pending_invite_by_token_hash(
        self, *, token_hash: str
    ) -> Invite | None:
        stmt = (
            update(Invite)
            .where(
                Invite.token_hash == token_hash,
                Invite.status == InviteStatus.PENDING,
                (Invite.expires_at.is_(None) | (Invite.expires_at > datetime.now(UTC))),
            )
            .values(status=InviteStatus.ACCEPTED)
            .returning(Invite)
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def mark_pending_invite_expired_by_token_hash(
        self, *, token_hash: str
    ) -> Invite | None:
        stmt = (
            update(Invite)
            .where(
                Invite.token_hash == token_hash,
                Invite.status == InviteStatus.PENDING,
                Invite.expires_at.is_not(None),
                Invite.expires_at <= datetime.now(UTC),
            )
            .values(status=InviteStatus.EXPIRED)
            .returning(Invite)
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def revoke_pending_invite(
        self, *, invite_id: UUID, organisation_id: UUID, revoked_by_user_id: UUID
    ) -> Invite | None:
        now = datetime.now(UTC)
        stmt = (
            update(Invite)
            .where(
                Invite.id == invite_id,
                Invite.organisation_id == organisation_id,
                Invite.status == InviteStatus.PENDING,
            )
            .values(
                status=InviteStatus.REVOKED,
                revoked_at=now,
                revoked_by_user_id=revoked_by_user_id,
            )
            .returning(Invite)
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def rotate_pending_invite_token(
        self,
        *,
        invite_id: UUID,
        organisation_id: UUID,
        new_token_hash: str,
        new_expires_at: datetime,
    ) -> Invite | None:
        stmt = (
            update(Invite)
            .where(
                Invite.id == invite_id,
                Invite.organisation_id == organisation_id,
                Invite.status == InviteStatus.PENDING,
                (Invite.expires_at.is_(None) | (Invite.expires_at > datetime.now(UTC))),
            )
            .values(token_hash=new_token_hash, expires_at=new_expires_at)
            .returning(Invite)
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def mark_pending_invite_expired_by_id(
        self, *, invite_id: UUID, organisation_id: UUID
    ) -> Invite | None:
        stmt = (
            update(Invite)
            .where(
                Invite.id == invite_id,
                Invite.organisation_id == organisation_id,
                Invite.status == InviteStatus.PENDING,
                Invite.expires_at.is_not(None),
                Invite.expires_at <= datetime.now(UTC),
            )
            .values(status=InviteStatus.EXPIRED)
            .returning(Invite)
        )
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

    async def get_invite_for_organisation_for_update(
        self, *, invite_id: UUID, organisation_id: UUID
    ) -> Invite | None:
        stmt = (
            select(Invite)
            .where(Invite.id == invite_id, Invite.organisation_id == organisation_id)
            .with_for_update()
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

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import and_, func, not_, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.invites.anonymisation import (
    SCRUBBED_INVITE_EMAIL_DOMAIN,
    SCRUBBED_INVITE_TOKEN_PREFIX,
    is_scrubbed_invite,
    scrubbed_invite_email,
    scrubbed_invite_token_hash,
)
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

    async def accept_pending_invite_by_token_hash(
        self, *, token_hash: str, now: datetime
    ) -> Invite | None:
        stmt = (
            update(Invite)
            .where(
                Invite.token_hash == token_hash,
                Invite.status == InviteStatus.PENDING,
                (Invite.expires_at.is_(None)) | (Invite.expires_at > now),
            )
            .values(status=InviteStatus.ACCEPTED)
            .returning(Invite)
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def mark_pending_invite_expired_by_token_hash(
        self, *, token_hash: str, now: datetime
    ) -> Invite | None:
        stmt = (
            update(Invite)
            .where(
                Invite.token_hash == token_hash,
                Invite.status == InviteStatus.PENDING,
                Invite.expires_at <= now,
            )
            .values(status=InviteStatus.EXPIRED)
            .returning(Invite)
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def revoke_pending_invite(
        self,
        *,
        invite_id: UUID,
        organisation_id: UUID,
        actor_user_id: UUID,
        now: datetime,
    ) -> Invite | None:
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
                revoked_by_user_id=actor_user_id,
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
        now: datetime,
    ) -> Invite | None:
        stmt = (
            update(Invite)
            .where(
                Invite.id == invite_id,
                Invite.organisation_id == organisation_id,
                Invite.status == InviteStatus.PENDING,
                (Invite.expires_at.is_(None)) | (Invite.expires_at > now),
            )
            .values(token_hash=new_token_hash, expires_at=new_expires_at)
            .returning(Invite)
            .execution_options(synchronize_session="fetch")
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def mark_pending_invite_expired_by_id(
        self, *, invite_id: UUID, organisation_id: UUID, now: datetime
    ) -> Invite | None:
        stmt = (
            update(Invite)
            .where(
                Invite.id == invite_id,
                Invite.organisation_id == organisation_id,
                Invite.status == InviteStatus.PENDING,
                Invite.expires_at <= now,
            )
            .values(status=InviteStatus.EXPIRED)
            .returning(Invite)
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def anonymise_completed_invites_older_than(
        self,
        *,
        accepted_before: datetime,
        expired_before: datetime,
        revoked_before: datetime,
        batch_size: int,
    ) -> int:
        """Replace completed invite PII/secrets with deterministic tombstones.

        The current schema keeps ``email`` and ``token_hash`` non-null and
        unique, so the
        safest backward-compatible retention step is irreversible in-place
        anonymisation rather than deletion or nullable-column migration. Already
        scrubbed tombstone rows are excluded in SQL so they cannot starve later
        eligible unsanitized rows when the batch is capped.
        """

        stmt = (
            select(Invite)
            .where(
                or_(
                    (
                        (Invite.status == InviteStatus.ACCEPTED)
                        & (Invite.updated_at < accepted_before)
                    ),
                    (
                        (Invite.status == InviteStatus.EXPIRED)
                        & (Invite.updated_at < expired_before)
                    ),
                    (
                        (Invite.status == InviteStatus.REVOKED)
                        & (Invite.updated_at < revoked_before)
                    ),
                ),
                not_(
                    and_(
                        Invite.email.endswith(f"@{SCRUBBED_INVITE_EMAIL_DOMAIN}"),
                        Invite.token_hash.startswith(
                            f"{SCRUBBED_INVITE_TOKEN_PREFIX}:"
                        ),
                    )
                ),
            )
            .order_by(Invite.updated_at.asc(), Invite.id.asc())
            .limit(batch_size)
        )
        rows = (await self.session.execute(stmt)).scalars().all()

        anonymised_count = 0
        for invite in rows:
            if is_scrubbed_invite(invite):
                continue
            invite.email = scrubbed_invite_email(invite.id)
            invite.token_hash = scrubbed_invite_token_hash(invite.id)
            anonymised_count += 1

        if anonymised_count:
            await self.session.flush()
        return anonymised_count

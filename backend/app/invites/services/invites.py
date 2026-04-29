from __future__ import annotations

from datetime import UTC, datetime, timedelta
from hashlib import sha256
from secrets import token_urlsafe
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import AuthenticatedPrincipal
from app.core.errors.exceptions import ConflictError, ForbiddenError, NotFoundError
from app.invites.models.invite import Invite, InviteStatus
from app.invites.repositories.invites import InviteRepository
from app.invites.services.delivery import InviteTokenSink, NoOpInviteTokenSink
from app.memberships.models.membership import Membership, MembershipRole
from app.memberships.services.memberships import MembershipService
from app.organisations.services.organisations import OrganisationService
from app.users.services.users import UserService


class InviteService:
    # Foundation default: a one-week validity window keeps invitations usable while
    # limiting long-lived pending tokens until dedicated lifecycle flows are added.
    DEFAULT_INVITE_TTL = timedelta(days=7)

    def __init__(
        self,
        session: AsyncSession,
        *,
        token_sink: InviteTokenSink | None = None,
    ) -> None:
        self.session = session
        self.invite_repository = InviteRepository(session)
        self.membership_service = MembershipService(session)
        self.organisation_service = OrganisationService(session)
        self.user_service = UserService(session)
        self.token_sink = token_sink or NoOpInviteTokenSink()

    @staticmethod
    def _token_hash(token: str) -> str:
        return sha256(token.encode("utf-8")).hexdigest()

    async def create_invite(
        self,
        *,
        organisation_id: UUID,
        actor_user_id: UUID,
        role: MembershipRole,
        email: str,
    ) -> Invite:
        if self.session.in_transaction():
            return await self._create_invite(
                organisation_id=organisation_id,
                actor_user_id=actor_user_id,
                role=role,
                email=email,
            )
        async with self.session.begin():
            return await self._create_invite(
                organisation_id=organisation_id,
                actor_user_id=actor_user_id,
                role=role,
                email=email,
            )

    async def _create_invite(
        self,
        *,
        organisation_id: UUID,
        actor_user_id: UUID,
        role: MembershipRole,
        email: str,
    ) -> Invite:
        actor = await self.user_service.get_user(actor_user_id)
        self.user_service.ensure_user_active(actor)
        organisation = await self.organisation_service.get_organisation(organisation_id)
        self.organisation_service.ensure_organisation_active(organisation)
        if role == MembershipRole.OWNER:
            raise ForbiddenError(detail="Owner role cannot be assigned via invite")

        membership_repo = self.membership_service.membership_repository
        actor_membership = await membership_repo.get_membership(
            user_id=actor_user_id,
            organisation_id=organisation_id,
        )
        if actor_membership is None or actor_membership.role not in {
            MembershipRole.OWNER,
            MembershipRole.ADMIN,
        }:
            raise ForbiddenError(detail="You are not allowed to invite users")
        if (
            actor_membership.role == MembershipRole.ADMIN
            and role == MembershipRole.ADMIN
        ):
            raise ForbiddenError(detail="Admin cannot assign admin role")

        token = token_urlsafe(32)
        expires_at = datetime.now(UTC) + self.DEFAULT_INVITE_TTL
        invite = await self.invite_repository.create_invite(
            email=email.strip().lower(),
            organisation_id=organisation_id,
            role=role,
            token_hash=self._token_hash(token),
            expires_at=expires_at,
        )
        await self.token_sink.deliver(invite=invite, raw_token=token)
        return invite

    async def accept_invite(
        self,
        *,
        token: str,
        identity: AuthenticatedPrincipal,
    ) -> Membership:
        token_hash = self._token_hash(token)
        if self.session.in_transaction():
            return await self._accept_invite_in_transaction(
                token_hash=token_hash,
                identity=identity,
            )
        async with self.session.begin():
            return await self._accept_invite_in_transaction(
                token_hash=token_hash,
                identity=identity,
            )

    @staticmethod
    def _normalize_utc(value: datetime | None) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)

    @staticmethod
    def _is_expired(*, expires_at: datetime | None) -> bool:
        normalized_expires_at = InviteService._normalize_utc(expires_at)
        if normalized_expires_at is None:
            return False
        return normalized_expires_at <= datetime.now(UTC)

    async def _accept_invite_in_transaction(
        self,
        *,
        token_hash: str,
        identity: AuthenticatedPrincipal,
    ) -> Membership:
        invite = await self.invite_repository.get_by_token_hash(token_hash)
        if invite is None:
            raise NotFoundError(detail="Invite not found")
        if invite.status != InviteStatus.PENDING:
            raise ConflictError(detail="Invite is no longer pending")

        if self._is_expired(expires_at=invite.expires_at):
            await self.invite_repository.mark_status(invite, InviteStatus.EXPIRED)
            raise ConflictError(detail="Invite has expired")

        if not identity.external_auth_id:
            raise ForbiddenError(detail="Authenticated identity is required")
        if identity.email is None or invite.email.lower() != identity.email.lower():
            raise ForbiddenError(
                detail="Invite email does not match authenticated user"
            )

        user = await self.user_service.get_or_create_current_user(identity=identity)
        self.user_service.ensure_user_active(user)
        organisation = await self.organisation_service.get_organisation(
            invite.organisation_id
        )
        self.organisation_service.ensure_organisation_active(organisation)
        membership = await self.membership_service.transfer_membership(
            user_id=user.id,
            organisation_id=invite.organisation_id,
            role=invite.role,
        )
        await self.invite_repository.mark_status(invite, InviteStatus.ACCEPTED)

        return membership

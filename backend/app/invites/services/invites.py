from __future__ import annotations

from hashlib import sha256
from secrets import token_urlsafe
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import AuthenticatedPrincipal
from app.core.errors.exceptions import ConflictError, ForbiddenError, NotFoundError
from app.invites.models.invite import Invite, InviteStatus
from app.invites.repositories.invites import InviteRepository
from app.memberships.models.membership import Membership, MembershipRole
from app.memberships.services.memberships import MembershipService
from app.organisations.services.organisations import OrganisationService
from app.users.repositories.users import UserRepository


class InviteService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.invite_repository = InviteRepository(session)
        self.membership_service = MembershipService(session)
        self.organisation_service = OrganisationService(session)
        self.user_repository = UserRepository(session)

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
        actor_is_superadmin: bool,
    ) -> tuple[Invite, str]:
        await self.organisation_service.get_organisation(organisation_id)

        if not actor_is_superadmin:
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
        invite = await self.invite_repository.create_invite(
            email=email.strip().lower(),
            organisation_id=organisation_id,
            role=role,
            token_hash=self._token_hash(token),
        )
        return invite, token

    async def accept_invite(
        self,
        *,
        token: str,
        identity: AuthenticatedPrincipal,
    ) -> Membership:
        token_hash = self._token_hash(token)
        invite = await self.invite_repository.get_by_token_hash(token_hash)
        if invite is None:
            raise NotFoundError(detail="Invite not found")
        if invite.status != InviteStatus.PENDING:
            raise ConflictError(detail="Invite is no longer pending")

        user = await self.user_repository.get_by_external_auth_id(
            identity.external_auth_id
        )
        if user is None:
            raise ConflictError(
                detail="Invite cannot be accepted until user projection exists"
            )

        if identity.email is None or invite.email.lower() != identity.email.lower():
            raise ForbiddenError(
                detail="Invite email does not match authenticated user"
            )

        async with self.session.begin():
            membership = await self.membership_service.transfer_membership(
                user_id=user.id,
                organisation_id=invite.organisation_id,
                role=invite.role,
            )
            await self.invite_repository.mark_status(invite, InviteStatus.ACCEPTED)

        return membership

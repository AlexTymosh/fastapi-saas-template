from __future__ import annotations

import secrets
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import AuthenticatedPrincipal
from app.core.errors.exceptions import BadRequestError, ForbiddenError, NotFoundError
from app.invites.models.invite import Invite, InviteStatus
from app.invites.repositories.invites import InviteRepository
from app.memberships.models.membership import MembershipRole
from app.memberships.services.memberships import MembershipService
from app.organisations.services.organisations import OrganisationService
from app.users.models.user import User
from app.users.services.users import UserService


class InviteService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.invite_repository = InviteRepository(session)
        self.user_service = UserService(session)
        self.membership_service = MembershipService(session)
        self.organisation_service = OrganisationService(session)

    async def create_invite(
        self,
        *,
        identity: AuthenticatedPrincipal,
        organisation_id: UUID,
        email: str,
        role: MembershipRole,
    ) -> Invite:
        if role == MembershipRole.OWNER:
            raise ForbiddenError(detail="Ownership transfer is not allowed via invites")

        actor = await self.user_service.provision_current_user(identity=identity)
        await self.organisation_service.get_organisation(organisation_id)
        await self.membership_service.ensure_user_can_invite(
            identity=identity,
            user_id=actor.id,
            organisation_id=organisation_id,
            role_to_assign=role,
        )

        token = secrets.token_urlsafe(32)
        return await self.invite_repository.create(
            email=email.lower(),
            organisation_id=organisation_id,
            role=role,
            token=token,
        )

    async def accept_invite(
        self,
        *,
        identity: AuthenticatedPrincipal,
        token: str,
    ) -> Invite:
        if identity.email is None:
            raise ForbiddenError(detail="Invite acceptance requires an email claim")

        async with self.session.begin():
            invite = await self.invite_repository.get_by_token(token=token)
            if invite is None:
                raise NotFoundError(detail="Invite not found")
            if invite.status != InviteStatus.PENDING:
                raise BadRequestError(detail="Invite is not pending")
            if invite.email.lower() != identity.email.lower():
                raise ForbiddenError(detail="Invite email does not match authenticated user")

            user = await self.user_service.get_or_create_current_user(identity)
            await self._transfer_membership(user=user, invite=invite)
            return await self.invite_repository.mark_accepted(invite)

    async def _transfer_membership(self, *, user: User, invite: Invite) -> None:
        await self.membership_service.transfer_user_membership(
            user_id=user.id,
            organisation_id=invite.organisation_id,
            role=invite.role,
        )

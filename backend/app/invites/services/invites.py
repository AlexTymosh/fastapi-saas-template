from __future__ import annotations

from datetime import UTC, datetime, timedelta
from hashlib import sha256
from secrets import token_urlsafe
from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.access_control.guards import ensure_email_verified, ensure_organisation_active
from app.audit.context import AuditContext
from app.audit.models.audit_event import AuditAction, AuditCategory, AuditTargetType
from app.audit.services.audit_events import AuditEventService
from app.core.auth import AuthenticatedPrincipal
from app.core.config.settings import get_settings
from app.core.errors.exceptions import ConflictError, ForbiddenError, NotFoundError
from app.core.logging import get_logger
from app.invites.models.invite import Invite, InviteStatus
from app.invites.repositories.invites import InviteRepository
from app.memberships.models.membership import Membership, MembershipRole
from app.memberships.services.memberships import MembershipService
from app.organisations.services.organisations import OrganisationService
from app.outbox.models.outbox_event import OutboxEventType
from app.outbox.services.outbox import OutboxService
from app.outbox.services.payload_crypto import OutboxPayloadCrypto
from app.users.services.users import UserService


class InviteService:
    log = get_logger(__name__)

    @staticmethod
    def _ensure_audit_actor_matches(
        *, actor_user_id: UUID, audit_context: AuditContext
    ) -> None:
        if audit_context.actor_user_id != actor_user_id:
            raise ValueError("Audit actor does not match action actor")

    DEFAULT_INVITE_TTL = timedelta(days=7)

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.invite_repository = InviteRepository(session)
        self.membership_service = MembershipService(session)
        self.organisation_service = OrganisationService(session)
        self.user_service = UserService(session)
        self.outbox_service = OutboxService(session)
        key = (
            get_settings().security.outbox_token_encryption_key
            or "MDEyMzQ1Njc4OWFiY2RlZjAxMjM0NTY3ODlhYmNkZWY="
        )
        self.payload_crypto = OutboxPayloadCrypto(key)

    @staticmethod
    def _token_hash(token: str) -> str:
        return sha256(token.encode("utf-8")).hexdigest()

    async def _get_actor_membership(
        self, *, organisation_id: UUID, actor_user_id: UUID
    ):
        actor_user = await self.user_service.get_user_by_id(actor_user_id)
        await self.user_service.ensure_user_is_active(actor_user)
        organisation = await self.organisation_service.get_organisation(organisation_id)
        ensure_organisation_active(organisation)
        actor_membership = (
            await self.membership_service.membership_repository.get_membership(
                user_id=actor_user_id, organisation_id=organisation_id
            )
        )
        if actor_membership is None:
            raise ForbiddenError(detail="You are not allowed to invite users")
        return actor_membership

    async def create_invite(
        self,
        *,
        organisation_id: UUID,
        actor_user_id: UUID,
        role: MembershipRole,
        email: str,
        audit_context: AuditContext,
    ) -> Invite:
        self._ensure_audit_actor_matches(
            actor_user_id=actor_user_id,
            audit_context=audit_context,
        )
        invite: Invite | None = None
        async with self.session.begin():
            if role == MembershipRole.OWNER:
                raise ForbiddenError(detail="Owner role cannot be assigned via invite")
            actor_membership = await self._get_actor_membership(
                organisation_id=organisation_id, actor_user_id=actor_user_id
            )
            if actor_membership.role not in {
                MembershipRole.OWNER,
                MembershipRole.ADMIN,
            }:
                raise ForbiddenError(detail="You are not allowed to invite users")
            if (
                actor_membership.role == MembershipRole.ADMIN
                and role == MembershipRole.ADMIN
            ):
                raise ForbiddenError(detail="Admin cannot assign admin role")
            normalized_email = email.strip().lower()
            if await self.invite_repository.get_pending_invite_by_email(
                organisation_id=organisation_id, email=normalized_email
            ):
                raise ConflictError(
                    detail="Pending invite already exists for this email"
                )
            token = token_urlsafe(32)
            expires_at = datetime.now(UTC) + self.DEFAULT_INVITE_TTL
            try:
                invite = await self.invite_repository.create_invite(
                    email=normalized_email,
                    organisation_id=organisation_id,
                    role=role,
                    token_hash=self._token_hash(token),
                    expires_at=expires_at,
                )
            except IntegrityError as exc:
                raise ConflictError(
                    detail="Pending invite already exists for this email"
                ) from exc
            await AuditEventService(self.session).record_event(
                audit_context=audit_context,
                category=AuditCategory.TENANT,
                action=AuditAction.INVITE_CREATED,
                target_type=AuditTargetType.INVITE,
                target_id=invite.id,
                metadata_json={
                    "organisation_id": str(organisation_id),
                    "invite_role": invite.role.value,
                },
            )
            await self.outbox_service.publish_event(
                event_type=OutboxEventType.INVITE_CREATED.value,
                aggregate_type="invite",
                aggregate_id=invite.id,
                payload_json={
                    "invite_id": str(invite.id),
                    "organisation_id": str(organisation_id),
                    "email": invite.email,
                    "encrypted_raw_token": self.payload_crypto.encrypt_token(token),
                    "purpose": "created",
                    "role": invite.role.value,
                },
            )
        assert invite is not None
        return invite

    async def accept_invite(
        self, *, token: str, identity: AuthenticatedPrincipal
    ) -> Membership:
        token_hash = self._token_hash(token)
        async with (
            self.session.begin()
            if not self.session.in_transaction()
            else _NoopContext()
        ):
            invite = await self.invite_repository.accept_pending_invite_by_token_hash(
                token_hash=token_hash
            )
            if invite is None:
                mark_expired = (
                    self.invite_repository.mark_pending_invite_expired_by_token_hash
                )
                expired_invite = await mark_expired(token_hash=token_hash)
                if expired_invite is not None:
                    raise ConflictError(detail="Invite has expired")
                existing_invite = await self.invite_repository.get_by_token_hash(
                    token_hash
                )
                if existing_invite is None:
                    raise NotFoundError(detail="Invite not found")
                raise ConflictError(detail="Invite is no longer pending")
            if identity.email is None or invite.email.lower() != identity.email.lower():
                raise ForbiddenError(
                    detail="Invite email does not match authenticated user"
                )
            ensure_email_verified(identity)
            user = await self.user_service.get_or_create_current_user(identity=identity)
            await self.user_service.ensure_user_is_active(user)
            organisation = await self.organisation_service.get_organisation(
                invite.organisation_id
            )
            ensure_organisation_active(organisation)
            membership = await self.membership_service.create_membership(
                user_id=user.id,
                organisation_id=invite.organisation_id,
                role=invite.role,
            )
            await self.invite_repository.mark_status(invite, InviteStatus.ACCEPTED)
            return membership

    async def revoke_invite(
        self,
        *,
        organisation_id: UUID,
        invite_id: UUID,
        actor_user_id: UUID,
        audit_context: AuditContext,
        reason: str | None = None,
    ) -> None:
        self._ensure_audit_actor_matches(
            actor_user_id=actor_user_id,
            audit_context=audit_context,
        )
        async with (
            self.session.begin()
            if not self.session.in_transaction()
            else _NoopContext()
        ):
            actor = await self._get_actor_membership(
                organisation_id=organisation_id, actor_user_id=actor_user_id
            )
            invite = await self.invite_repository.get_invite_for_organisation(
                invite_id=invite_id, organisation_id=organisation_id
            )
            if invite is None:
                raise NotFoundError(detail="Invite not found")
            if invite.status != InviteStatus.PENDING:
                raise ConflictError(detail="Only pending invite can be revoked")
            if actor.role == MembershipRole.MEMBER:
                raise ForbiddenError(detail="You are not allowed to revoke invites")
            if (
                actor.role == MembershipRole.ADMIN
                and invite.role == MembershipRole.ADMIN
            ):
                raise ForbiddenError(detail="Admin can revoke member invites only")
            previous_status = invite.status
            revoked = await self.invite_repository.revoke_pending_invite(
                invite_id=invite_id,
                organisation_id=organisation_id,
                revoked_by_user_id=actor_user_id,
            )
            if revoked is None:
                raise ConflictError(detail="Only pending invite can be revoked")
            invite = revoked
            await AuditEventService(self.session).record_event(
                audit_context=audit_context,
                category=AuditCategory.TENANT,
                action=AuditAction.INVITE_REVOKED,
                target_type=AuditTargetType.INVITE,
                target_id=invite.id,
                reason=reason,
                metadata_json={
                    "organisation_id": str(organisation_id),
                    "invite_role": invite.role.value,
                    "invite_status_before": previous_status.value,
                },
            )

    async def resend_invite(
        self,
        *,
        organisation_id: UUID,
        invite_id: UUID,
        actor_user_id: UUID,
        audit_context: AuditContext,
    ) -> Invite:
        self._ensure_audit_actor_matches(
            actor_user_id=actor_user_id,
            audit_context=audit_context,
        )

        async with self.session.begin():
            actor = await self._get_actor_membership(
                organisation_id=organisation_id, actor_user_id=actor_user_id
            )
            invite = await self.invite_repository.get_invite_for_organisation(
                invite_id=invite_id, organisation_id=organisation_id
            )
            if invite is None:
                raise NotFoundError(detail="Invite not found")
            if invite.status != InviteStatus.PENDING:
                raise ConflictError(detail="Only pending invite can be resent")
            if actor.role == MembershipRole.MEMBER:
                raise ForbiddenError(detail="You are not allowed to resend invites")
            if (
                actor.role == MembershipRole.ADMIN
                and invite.role == MembershipRole.ADMIN
            ):
                raise ForbiddenError(detail="Admin can resend member invites only")

            token = token_urlsafe(32)
            token_hash = self._token_hash(token)
            expires_at = datetime.now(UTC) + self.DEFAULT_INVITE_TTL

            rotated = await self.invite_repository.rotate_pending_invite_token(
                invite_id=invite_id,
                organisation_id=organisation_id,
                new_token_hash=token_hash,
                new_expires_at=expires_at,
            )
            if rotated is None:
                expired_invite = (
                    await self.invite_repository.mark_pending_invite_expired_by_id(
                        invite_id=invite_id,
                        organisation_id=organisation_id,
                    )
                )
                if expired_invite is not None:
                    raise ConflictError(detail="Invite has expired")
                raise ConflictError(detail="Only pending invite can be resent")
            invite = rotated
            await AuditEventService(self.session).record_event(
                audit_context=audit_context,
                category=AuditCategory.TENANT,
                action=AuditAction.INVITE_RESENT,
                target_type=AuditTargetType.INVITE,
                target_id=invite.id,
                metadata_json={
                    "organisation_id": str(organisation_id),
                    "invite_role": invite.role.value,
                },
            )
            await self.outbox_service.publish_event(
                event_type=OutboxEventType.INVITE_RESEND.value,
                aggregate_type="invite",
                aggregate_id=invite.id,
                payload_json={
                    "invite_id": str(invite.id),
                    "organisation_id": str(organisation_id),
                    "email": invite.email,
                    "encrypted_raw_token": self.payload_crypto.encrypt_token(token),
                    "purpose": "resent",
                    "role": invite.role.value,
                },
            )

        return invite

    @staticmethod
    def _normalize_utc(value: datetime | None) -> datetime | None:
        if value is None:
            return None
        return (
            value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
        )

    @staticmethod
    def _is_expired(*, expires_at: datetime | None) -> bool:
        normalized_expires_at = InviteService._normalize_utc(expires_at)
        return (
            normalized_expires_at is not None
            and normalized_expires_at <= datetime.now(UTC)
        )


class _NoopContext:
    async def __aenter__(self):
        return None

    async def __aexit__(self, exc_type, exc, tb):
        return False

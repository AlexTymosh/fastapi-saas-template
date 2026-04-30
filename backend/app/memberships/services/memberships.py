from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.access_control.guards import ensure_organisation_active
from app.audit.context import AuditContext
from app.audit.models.audit_event import AuditAction, AuditCategory, AuditTargetType
from app.audit.services.audit_events import AuditEventService
from app.core.errors.exceptions import ConflictError, ForbiddenError, NotFoundError
from app.memberships.models.membership import Membership, MembershipRole
from app.memberships.repositories.memberships import MembershipRepository
from app.organisations.services.organisations import OrganisationService
from app.users.services.users import UserService


@dataclass(frozen=True)
class OrganisationDirectoryMember:
    display_name: str
    role_label: str


class MembershipService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.membership_repository = MembershipRepository(session)
        self.user_service = UserService(session)
        self.organisation_service = OrganisationService(session)

    async def create_membership(
        self,
        *,
        user_id: UUID,
        organisation_id: UUID,
        role: MembershipRole,
    ) -> Membership:
        if self.session.in_transaction():
            return await self._create_membership(
                user_id=user_id,
                organisation_id=organisation_id,
                role=role,
            )
        async with self.session.begin():
            return await self._create_membership(
                user_id=user_id,
                organisation_id=organisation_id,
                role=role,
            )

    async def _create_membership(
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

    async def change_membership_role(
        self,
        *,
        organisation_id: UUID,
        actor_user_id: UUID,
        audit_context: AuditContext,
        membership_id: UUID,
        role: MembershipRole,
    ) -> Membership:
        self._ensure_audit_actor_matches(
            actor_user_id=actor_user_id, audit_context=audit_context
        )
        if self.session.in_transaction():
            return await self._change_membership_role(
                organisation_id=organisation_id,
                actor_user_id=actor_user_id,
                audit_context=audit_context,
                membership_id=membership_id,
                role=role,
            )
        async with self.session.begin():
            return await self._change_membership_role(
                organisation_id=organisation_id,
                actor_user_id=actor_user_id,
                audit_context=audit_context,
                membership_id=membership_id,
                role=role,
            )

    async def _change_membership_role(
        self,
        *,
        organisation_id: UUID,
        actor_user_id: UUID,
        audit_context: AuditContext,
        membership_id: UUID,
        role: MembershipRole,
    ) -> Membership:
        actor_user = await self.user_service.get_user_by_id(actor_user_id)
        await self.user_service.ensure_user_is_active(actor_user)
        organisation = await self.organisation_service.get_organisation(organisation_id)
        ensure_organisation_active(organisation)
        actor_membership = await self.membership_repository.get_membership(
            user_id=actor_user_id,
            organisation_id=organisation_id,
        )
        if actor_membership is None:
            raise ForbiddenError(detail="You are not a member of this organisation")
        target_membership = await self.get_membership_for_organisation(
            membership_id=membership_id,
            organisation_id=organisation_id,
        )
        if role == MembershipRole.OWNER:
            raise ForbiddenError(detail="Tenant API cannot assign owner role")
        if target_membership.role == MembershipRole.OWNER:
            raise ForbiddenError(detail="Owner role cannot be modified")
        if actor_membership.role != MembershipRole.OWNER:
            raise ForbiddenError(detail="Only owner can change membership roles")
        old_role = target_membership.role
        updated = await self.membership_repository.update_role(
            target_membership, role=role
        )
        await AuditEventService(self.session).record_event(
            audit_context=audit_context,
            category=AuditCategory.TENANT,
            action=AuditAction.MEMBERSHIP_ROLE_CHANGED,
            target_type=AuditTargetType.MEMBERSHIP,
            target_id=updated.id,
            metadata_json={
                "organisation_id": str(organisation_id),
                "old_role": old_role.value,
                "new_role": updated.role.value,
            },
        )
        return updated

    async def remove_membership(
        self,
        *,
        organisation_id: UUID,
        actor_user_id: UUID,
        audit_context: AuditContext,
        membership_id: UUID,
    ) -> Membership:
        self._ensure_audit_actor_matches(
            actor_user_id=actor_user_id, audit_context=audit_context
        )
        if self.session.in_transaction():
            return await self._remove_membership(
                organisation_id=organisation_id,
                actor_user_id=actor_user_id,
                audit_context=audit_context,
                membership_id=membership_id,
            )
        async with self.session.begin():
            return await self._remove_membership(
                organisation_id=organisation_id,
                actor_user_id=actor_user_id,
                audit_context=audit_context,
                membership_id=membership_id,
            )

    async def _remove_membership(
        self,
        *,
        organisation_id: UUID,
        actor_user_id: UUID,
        audit_context: AuditContext,
        membership_id: UUID,
    ) -> Membership:
        actor_user = await self.user_service.get_user_by_id(actor_user_id)
        await self.user_service.ensure_user_is_active(actor_user)
        organisation = await self.organisation_service.get_organisation(organisation_id)
        ensure_organisation_active(organisation)
        actor_membership = await self.membership_repository.get_membership(
            user_id=actor_user_id,
            organisation_id=organisation_id,
        )
        if actor_membership is None:
            raise ForbiddenError(detail="You are not a member of this organisation")
        target_membership = await self.get_membership_for_organisation(
            membership_id=membership_id,
            organisation_id=organisation_id,
        )
        if target_membership.role == MembershipRole.OWNER:
            raise ForbiddenError(detail="Owner membership cannot be removed")
        removed = None
        if actor_membership.role == MembershipRole.OWNER:
            removed = await self.membership_repository.deactivate_membership(
                target_membership
            )
        elif actor_membership.role == MembershipRole.ADMIN:
            if target_membership.role != MembershipRole.MEMBER:
                raise ForbiddenError(detail="Admin can remove only members")
            removed = await self.membership_repository.deactivate_membership(
                target_membership
            )
        else:
            raise ForbiddenError(detail="You are not allowed to remove memberships")
        await AuditEventService(self.session).record_event(
            audit_context=audit_context,
            category=AuditCategory.TENANT,
            action=AuditAction.MEMBERSHIP_REMOVED,
            target_type=AuditTargetType.MEMBERSHIP,
            target_id=removed.id,
            metadata_json={
                "organisation_id": str(organisation_id),
                "removed_user_id": str(removed.user_id),
                "previous_role": removed.role.value,
            },
        )
        return removed

    async def get_membership_for_organisation(
        self,
        *,
        membership_id: UUID,
        organisation_id: UUID,
    ) -> Membership:
        membership = await self.membership_repository.get_membership_by_id(
            membership_id=membership_id,
            organisation_id=organisation_id,
        )
        if membership is None:
            raise NotFoundError(detail="Membership not found")
        return membership

    async def transfer_membership(
        self,
        *,
        user_id: UUID,
        organisation_id: UUID,
        role: MembershipRole,
    ) -> Membership:
        if self.session.in_transaction():
            return await self._transfer_membership(
                user_id=user_id,
                organisation_id=organisation_id,
                role=role,
            )
        async with self.session.begin():
            return await self._transfer_membership(
                user_id=user_id,
                organisation_id=organisation_id,
                role=role,
            )

    async def _transfer_membership(
        self,
        *,
        user_id: UUID,
        organisation_id: UUID,
        role: MembershipRole,
    ) -> Membership:
        existing = await self.membership_repository.get_membership_for_user(
            user_id=user_id
        )
        if existing is not None:
            if existing.role == MembershipRole.OWNER:
                owner_count = await self.membership_repository.count_active_owners(
                    organisation_id=existing.organisation_id
                )
                if owner_count <= 1:
                    raise ConflictError(
                        detail="Organisation must always have at least one owner"
                    )
            await self.membership_repository.deactivate_membership(existing)

        return await self.membership_repository.create_membership(
            user_id=user_id,
            organisation_id=organisation_id,
            role=role,
        )

    @staticmethod
    def _ensure_audit_actor_matches(
        *, actor_user_id: UUID, audit_context: AuditContext
    ) -> None:
        if audit_context.actor_user_id != actor_user_id:
            raise ValueError("Audit actor does not match action actor")

    async def list_directory_members_for_user(
        self,
        *,
        organisation_id: UUID,
        actor_user_id: UUID,
    ) -> list[OrganisationDirectoryMember]:
        actor_user = await self.user_service.get_user_by_id(actor_user_id)
        await self.user_service.ensure_user_is_active(actor_user)
        organisation = await self.organisation_service.get_organisation(organisation_id)
        ensure_organisation_active(organisation)
        actor_membership = await self.membership_repository.get_membership(
            user_id=actor_user_id,
            organisation_id=organisation_id,
        )
        if actor_membership is None:
            raise ForbiddenError(detail="You are not a member of this organisation")
        items = (
            await self.membership_repository.list_directory_members_for_organisation(
                organisation_id=organisation_id,
            )
        )
        return [
            OrganisationDirectoryMember(
                display_name=(
                    f"{(first_name or '').strip()} {(last_name or '').strip()}".strip()
                    or "Organisation member"
                ),
                role_label="Organisation member",
            )
            for first_name, last_name in items
        ]

    async def list_memberships_for_management(
        self,
        *,
        organisation_id: UUID,
        actor_user_id: UUID,
    ) -> list[Membership]:
        actor_user = await self.user_service.get_user_by_id(actor_user_id)
        await self.user_service.ensure_user_is_active(actor_user)
        organisation = await self.organisation_service.get_organisation(organisation_id)
        ensure_organisation_active(organisation)
        actor_membership = await self.membership_repository.get_membership(
            user_id=actor_user_id,
            organisation_id=organisation_id,
        )
        if actor_membership is None or actor_membership.role not in {
            MembershipRole.OWNER,
            MembershipRole.ADMIN,
        }:
            raise ForbiddenError(
                detail="You are not allowed to view organisation memberships"
            )
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

    async def ensure_owner_invariant_before_deactivation(
        self,
        membership: Membership,
    ) -> None:
        if membership.role != MembershipRole.OWNER:
            return
        owner_count = await self.membership_repository.count_active_owners(
            organisation_id=membership.organisation_id
        )
        if owner_count <= 1:
            raise ConflictError(
                detail="Organisation must always have at least one owner"
            )

    async def deactivate_membership(self, membership: Membership) -> Membership:
        if self.session.in_transaction():
            return await self._deactivate_membership(membership)
        async with self.session.begin():
            return await self._deactivate_membership(membership)

    async def _deactivate_membership(self, membership: Membership) -> Membership:
        await self.ensure_owner_invariant_before_deactivation(membership)
        return await self.membership_repository.deactivate_membership(membership)

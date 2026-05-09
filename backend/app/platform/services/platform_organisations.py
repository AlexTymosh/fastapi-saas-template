from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.context import AuditContext
from app.audit.models.audit_event import AuditAction, AuditCategory, AuditTargetType
from app.audit.services.audit_events import AuditEventService
from app.core.errors.exceptions import ConflictError, NotFoundError
from app.core.platform.actors import PlatformActor
from app.memberships.services.memberships import MembershipService
from app.organisations.models.organisation import Organisation, OrganisationStatus
from app.organisations.repositories.organisations import OrganisationRepository
from app.organisations.services.organisations import OrganisationService


class PlatformOrganisationsService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.organisation_repository = OrganisationRepository(session)
        self.membership_service = MembershipService(session)
        self.audit_service = AuditEventService(session)

    async def list_organisations(
        self, *, limit: int, offset: int
    ) -> tuple[list[Organisation], int]:
        return await self.organisation_repository.list_paginated(
            limit=limit,
            offset=offset,
            include_deleted=True,
        )

    async def get_organisation(self, organisation_id: UUID) -> Organisation:
        org = await self.organisation_repository.get_by_id(
            organisation_id,
            include_deleted=True,
        )
        if org is None:
            raise NotFoundError(detail="Organisation not found")
        return org

    async def suspend_organisation(
        self,
        *,
        organisation_id: UUID,
        actor: PlatformActor,
        reason: str,
        audit_context: AuditContext,
    ) -> Organisation:
        return await self._suspend_organisation(
            organisation_id=organisation_id,
            actor=actor,
            reason=reason,
            audit_context=audit_context,
        )

    async def _suspend_organisation(
        self,
        *,
        organisation_id: UUID,
        actor: PlatformActor,
        reason: str,
        audit_context: AuditContext,
    ) -> Organisation:
        _ = actor
        org = await self.get_organisation(organisation_id)
        if org.status == OrganisationStatus.SUSPENDED:
            raise ConflictError(detail="Organisation already suspended")
        org = await self.organisation_repository.set_status(
            org,
            status=OrganisationStatus.SUSPENDED,
            suspended_at=datetime.now(UTC),
            suspended_reason=reason,
        )
        await self.audit_service.record_event(
            audit_context=audit_context,
            category=AuditCategory.PLATFORM,
            action=AuditAction.ORGANISATION_SUSPENDED,
            target_type=AuditTargetType.ORGANISATION,
            target_id=org.id,
            reason=reason,
        )
        return org

    async def restore_organisation(
        self,
        *,
        organisation_id: UUID,
        actor: PlatformActor,
        reason: str,
        audit_context: AuditContext,
    ) -> Organisation:
        return await self._restore_organisation(
            organisation_id=organisation_id,
            actor=actor,
            reason=reason,
            audit_context=audit_context,
        )

    async def _restore_organisation(
        self,
        *,
        organisation_id: UUID,
        actor: PlatformActor,
        reason: str,
        audit_context: AuditContext,
    ) -> Organisation:
        _ = actor
        org = await self.get_organisation(organisation_id)
        if org.status == OrganisationStatus.ACTIVE:
            raise ConflictError(detail="Organisation already active")
        org = await self.organisation_repository.set_status(
            org,
            status=OrganisationStatus.ACTIVE,
            suspended_at=None,
            suspended_reason=None,
        )
        await self.audit_service.record_event(
            audit_context=audit_context,
            category=AuditCategory.PLATFORM,
            action=AuditAction.ORGANISATION_RESTORED,
            target_type=AuditTargetType.ORGANISATION,
            target_id=org.id,
            reason=reason,
        )
        return org

    async def correct_organisation_profile(
        self,
        *,
        organisation_id: UUID,
        actor: PlatformActor,
        name: str | None,
        slug: str | None,
        reason: str,
        audit_context: AuditContext,
    ) -> Organisation:
        return await self._correct_organisation_profile(
            organisation_id=organisation_id,
            actor=actor,
            name=name,
            slug=slug,
            reason=reason,
            audit_context=audit_context,
        )

    async def _correct_organisation_profile(
        self,
        *,
        organisation_id: UUID,
        actor: PlatformActor,
        name: str | None,
        slug: str | None,
        reason: str,
        audit_context: AuditContext,
    ) -> Organisation:
        _ = actor
        org = await self.get_organisation(organisation_id)
        normalized_name = (
            OrganisationService.normalize_name(name) if name is not None else None
        )
        normalized_slug = (
            OrganisationService.normalize_slug(slug) if slug is not None else None
        )
        changed_fields: list[str] = []
        old_name = org.name
        old_slug = org.slug
        if normalized_name is not None and normalized_name != org.name:
            changed_fields.append("name")
        if normalized_slug is not None and normalized_slug != org.slug:
            changed_fields.append("slug")
        if not changed_fields:
            raise ConflictError(detail="No profile changes")

        try:
            org = await self.organisation_repository.update_details(
                org,
                name=normalized_name if "name" in changed_fields else None,
                slug=normalized_slug if "slug" in changed_fields else None,
            )
        except IntegrityError as exc:
            raise ConflictError(detail="Organisation slug already exists") from exc

        metadata_json: dict[str, object] = {
            "changed_fields": changed_fields,
            "correction_type": "platform_profile_correction",
        }
        if "name" in changed_fields:
            metadata_json["old_name"] = old_name
            metadata_json["new_name"] = org.name
        if "slug" in changed_fields:
            metadata_json["old_slug"] = old_slug
            metadata_json["new_slug"] = org.slug

        await self.audit_service.record_event(
            audit_context=audit_context,
            category=AuditCategory.PLATFORM,
            action=AuditAction.ORGANISATION_UPDATED,
            target_type=AuditTargetType.ORGANISATION,
            target_id=org.id,
            reason=reason,
            metadata_json=metadata_json,
        )
        return org

    async def emergency_replace_organisation_owner(
        self,
        *,
        organisation_id: UUID,
        source_owner_membership_id: UUID,
        replacement_membership_id: UUID,
        actor: PlatformActor,
        reason: str,
        audit_context: AuditContext,
    ):
        """
        Internal-only emergency correction flow until platform API is introduced.
        """
        _ = actor
        replacement = await self.membership_service.replace_owner_membership(
            organisation_id=organisation_id,
            source_owner_membership_id=source_owner_membership_id,
            replacement_membership_id=replacement_membership_id,
        )
        await self.audit_service.record_event(
            audit_context=audit_context,
            category=AuditCategory.PLATFORM,
            action=AuditAction.MEMBERSHIP_ROLE_CHANGED,
            target_type=AuditTargetType.MEMBERSHIP,
            target_id=replacement.id,
            reason=reason,
            metadata_json={
                "organisation_id": str(organisation_id),
                "correction_type": "emergency_owner_replacement",
                "source_owner_membership_id": str(source_owner_membership_id),
                "replacement_membership_id": str(replacement_membership_id),
            },
        )
        return replacement

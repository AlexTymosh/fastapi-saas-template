from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.context import AuditContext
from app.audit.models.audit_event import AuditAction, AuditCategory, AuditTargetType
from app.audit.services.audit_events import AuditEventService
from app.core.errors.exceptions import ConflictError, NotFoundError
from app.core.platform.actors import PlatformActor
from app.organisations.models.organisation import Organisation, OrganisationStatus
from app.organisations.services.organisations import OrganisationService


class PlatformOrganisationsService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list_organisations(
        self, *, limit: int, offset: int
    ) -> tuple[list[Organisation], int]:
        rows = (
            (
                await self.session.execute(
                    select(Organisation).offset(offset).limit(limit)
                )
            )
            .scalars()
            .all()
        )
        total = (
            await self.session.execute(select(func.count()).select_from(Organisation))
        ).scalar_one()
        return list(rows), int(total)

    async def get_organisation(self, organisation_id: UUID) -> Organisation:
        org = await self.session.get(Organisation, organisation_id)
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
        if self.session.in_transaction():
            return await self._suspend_organisation(
                organisation_id=organisation_id,
                actor=actor,
                reason=reason,
                audit_context=audit_context,
            )
        async with self.session.begin():
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
        org.status = OrganisationStatus.SUSPENDED
        org.suspended_at = datetime.now(UTC)
        org.suspended_reason = reason
        await AuditEventService(self.session).record_event(
            audit_context=audit_context,
            category=AuditCategory.PLATFORM,
            action=AuditAction.ORGANISATION_SUSPENDED,
            target_type=AuditTargetType.ORGANISATION,
            target_id=org.id,
            reason=reason,
        )
        await self.session.flush()
        return org

    async def restore_organisation(
        self,
        *,
        organisation_id: UUID,
        actor: PlatformActor,
        reason: str,
        audit_context: AuditContext,
    ) -> Organisation:
        if self.session.in_transaction():
            return await self._restore_organisation(
                organisation_id=organisation_id,
                actor=actor,
                reason=reason,
                audit_context=audit_context,
            )
        async with self.session.begin():
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
        org.status = OrganisationStatus.ACTIVE
        org.suspended_at = None
        org.suspended_reason = None
        await AuditEventService(self.session).record_event(
            audit_context=audit_context,
            category=AuditCategory.PLATFORM,
            action=AuditAction.ORGANISATION_RESTORED,
            target_type=AuditTargetType.ORGANISATION,
            target_id=org.id,
            reason=reason,
        )
        await self.session.flush()
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
        if self.session.in_transaction():
            return await self._correct_organisation_profile(
                organisation_id=organisation_id,
                actor=actor,
                name=name,
                slug=slug,
                reason=reason,
                audit_context=audit_context,
            )
        async with self.session.begin():
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
        changed = False
        if normalized_name is not None and normalized_name != org.name:
            org.name = normalized_name
            changed = True
        if normalized_slug is not None and normalized_slug != org.slug:
            org.slug = normalized_slug
            changed = True
        if not changed:
            raise ConflictError(detail="No profile changes")
        try:
            await self.session.flush()
        except IntegrityError as exc:
            raise ConflictError(detail="Organisation slug already exists") from exc
        await AuditEventService(self.session).record_event(
            audit_context=audit_context,
            category=AuditCategory.PLATFORM,
            action=AuditAction.ORGANISATION_UPDATED,
            target_type=AuditTargetType.ORGANISATION,
            target_id=org.id,
            reason=reason,
        )
        return org

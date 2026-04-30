from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.models.audit_event import AuditAction, AuditCategory, AuditTargetType
from app.audit.services.audit_events import AuditEventService
from app.core.errors.exceptions import ConflictError, NotFoundError
from app.core.platform.actors import PlatformActor
from app.organisations.models.organisation import Organisation, OrganisationStatus
from app.organisations.services.organisations import OrganisationService


class PlatformOrganisationsService:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def list_organisations(self, limit: int, offset: int):
        from sqlalchemy import func, select

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
        return rows, total

    async def get_organisation(self, organisation_id: UUID) -> Organisation:
        org = await self.session.get(Organisation, organisation_id)
        if org is None:
            raise NotFoundError(detail="Organisation not found")
        return org

    async def suspend_organisation(
        self, organisation_id: UUID, actor: PlatformActor, reason: str, audit_context
    ):
        async def _op():
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
            return org

        if self.session.in_transaction():
            return await _op()
        async with self.session.begin():
            return await _op()

    async def restore_organisation(
        self, organisation_id: UUID, actor: PlatformActor, reason: str, audit_context
    ):
        async def _op():
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
            return org

        if self.session.in_transaction():
            return await _op()
        async with self.session.begin():
            return await _op()

    async def correct_organisation_profile(
        self,
        organisation_id: UUID,
        actor: PlatformActor,
        name: str | None,
        slug: str | None,
        reason: str,
        audit_context,
    ):
        async def _op():
            org = await self.get_organisation(organisation_id)
            changed = False
            if name is not None:
                normalized_name = name.strip()
                if not normalized_name:
                    raise ValueError("Organisation name cannot be blank")
                if normalized_name != org.name:
                    org.name = normalized_name
                    changed = True
            if slug is not None:
                normalized_slug = OrganisationService.normalize_slug(slug)
                if normalized_slug != org.slug:
                    org.slug = normalized_slug
                    changed = True
            if not changed:
                raise ConflictError(detail="No profile changes")
            await AuditEventService(self.session).record_event(
                audit_context=audit_context,
                category=AuditCategory.PLATFORM,
                action=AuditAction.ORGANISATION_UPDATED,
                target_type=AuditTargetType.ORGANISATION,
                target_id=org.id,
                reason=reason,
            )
            return org

        try:
            if self.session.in_transaction():
                return await _op()
            async with self.session.begin():
                return await _op()
        except IntegrityError as exc:
            raise ConflictError(detail="Organisation slug already exists") from exc

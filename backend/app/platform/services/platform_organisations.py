from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.context import AuditContext
from app.audit.models.audit_event import AuditAction, AuditCategory, AuditTargetType
from app.audit.services.audit_events import AuditEventService
from app.core.errors.exceptions import ConflictError, NotFoundError
from app.organisations.models.organisation import OrganisationStatus
from app.organisations.repositories.organisations import OrganisationRepository


class PlatformOrganisationsService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.organisations = OrganisationRepository(session)

    async def suspend(self, *, organisation_id: UUID, reason: str, audit_context: AuditContext):
        organisation = await self.organisations.get_by_id(organisation_id)
        if organisation is None:
            raise NotFoundError(detail="Organisation not found")
        if organisation.status == OrganisationStatus.SUSPENDED.value:
            raise ConflictError(detail="Organisation already suspended")
        organisation.status = OrganisationStatus.SUSPENDED.value
        organisation.suspended_at = datetime.now(UTC)
        organisation.suspended_reason = reason.strip()
        await AuditEventService(self.session).record_event(audit_context=audit_context, category=AuditCategory.PLATFORM, action=AuditAction.ORGANISATION_SUSPENDED, target_type=AuditTargetType.ORGANISATION, target_id=organisation.id, reason=reason.strip())
        await self.session.flush()
        return organisation

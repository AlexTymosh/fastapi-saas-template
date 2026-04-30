from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.requests import Request

from app.audit.context import build_audit_context_from_request
from app.audit.models.audit_event import AuditAction, AuditCategory, AuditTargetType
from app.audit.services.audit_events import AuditEventService
from app.core.db import get_db_session
from app.core.errors.exceptions import ConflictError, NotFoundError
from app.core.platform import PlatformPermission, require_platform_permission
from app.organisations.models.organisation import Organisation, OrganisationStatus
from app.platform.schemas.platform_organisations import (
    PlatformOrganisationPatchRequest,
    PlatformOrganisationResponse,
)
from app.platform.schemas.platform_users import ReasonRequest

router = APIRouter(prefix="/platform/organisations", tags=["platform"])


@router.get("", response_model=list[PlatformOrganisationResponse])
async def list_platform_orgs(
    _: Annotated[
        object,
        Depends(require_platform_permission(PlatformPermission.ORGANISATIONS_READ)),
    ],
    db_session: Annotated[AsyncSession, Depends(get_db_session)],
) -> list[PlatformOrganisationResponse]:
    result = await db_session.execute(select(Organisation).limit(100))
    return [
        PlatformOrganisationResponse.model_validate(org)
        for org in result.scalars().all()
    ]


@router.get("/{organisation_id}", response_model=PlatformOrganisationResponse)
async def get_platform_org(
    organisation_id: UUID,
    _: Annotated[
        object,
        Depends(require_platform_permission(PlatformPermission.ORGANISATIONS_READ)),
    ],
    db_session: Annotated[AsyncSession, Depends(get_db_session)],
) -> PlatformOrganisationResponse:
    org = await db_session.get(Organisation, organisation_id)
    if org is None:
        raise NotFoundError(detail="Organisation not found")
    return PlatformOrganisationResponse.model_validate(org)


@router.post("/{organisation_id}/suspend", response_model=PlatformOrganisationResponse)
async def suspend_platform_org(
    organisation_id: UUID,
    payload: ReasonRequest,
    actor: Annotated[
        object,
        Depends(require_platform_permission(PlatformPermission.ORGANISATIONS_SUSPEND)),
    ],
    request: Request,
    db_session: Annotated[AsyncSession, Depends(get_db_session)],
) -> PlatformOrganisationResponse:
    org = await db_session.get(Organisation, organisation_id)
    if org is None:
        raise NotFoundError(detail="Organisation not found")
    if org.status == OrganisationStatus.SUSPENDED:
        raise ConflictError(detail="Organisation already suspended")
    async with db_session.begin():
        org.status = OrganisationStatus.SUSPENDED
        org.suspended_at = datetime.now(UTC)
        org.suspended_reason = payload.reason
        await AuditEventService(db_session).record_event(
            audit_context=build_audit_context_from_request(
                actor_user_id=actor.user.id, request=request
            ),
            category=AuditCategory.PLATFORM,
            action=AuditAction.ORGANISATION_SUSPENDED,
            target_type=AuditTargetType.ORGANISATION,
            target_id=org.id,
            reason=payload.reason,
        )
    await db_session.refresh(org)
    return PlatformOrganisationResponse.model_validate(org)


@router.post("/{organisation_id}/restore", response_model=PlatformOrganisationResponse)
async def restore_platform_org(
    organisation_id: UUID,
    payload: ReasonRequest,
    actor: Annotated[
        object,
        Depends(require_platform_permission(PlatformPermission.ORGANISATIONS_RESTORE)),
    ],
    request: Request,
    db_session: Annotated[AsyncSession, Depends(get_db_session)],
) -> PlatformOrganisationResponse:
    org = await db_session.get(Organisation, organisation_id)
    if org is None:
        raise NotFoundError(detail="Organisation not found")
    if org.status == OrganisationStatus.ACTIVE:
        raise ConflictError(detail="Organisation already active")
    async with db_session.begin():
        org.status = OrganisationStatus.ACTIVE
        org.suspended_at = None
        org.suspended_reason = None
        await AuditEventService(db_session).record_event(
            audit_context=build_audit_context_from_request(
                actor_user_id=actor.user.id, request=request
            ),
            category=AuditCategory.PLATFORM,
            action=AuditAction.ORGANISATION_RESTORED,
            target_type=AuditTargetType.ORGANISATION,
            target_id=org.id,
            reason=payload.reason,
        )
    await db_session.refresh(org)
    return PlatformOrganisationResponse.model_validate(org)


@router.patch("/{organisation_id}", response_model=PlatformOrganisationResponse)
async def patch_platform_org(
    organisation_id: UUID,
    payload: PlatformOrganisationPatchRequest,
    actor: Annotated[
        object,
        Depends(
            require_platform_permission(
                PlatformPermission.ORGANISATIONS_CORRECT_PROFILE
            )
        ),
    ],
    request: Request,
    db_session: Annotated[AsyncSession, Depends(get_db_session)],
) -> PlatformOrganisationResponse:
    org = await db_session.get(Organisation, organisation_id)
    if org is None:
        raise NotFoundError(detail="Organisation not found")
    changed = False
    if payload.name is not None and payload.name != org.name:
        org.name = payload.name.strip()
        changed = True
    if payload.slug is not None and payload.slug != org.slug:
        org.slug = payload.slug.strip().lower()
        changed = True
    if not changed:
        raise ConflictError(detail="No profile changes")
    async with db_session.begin():
        await AuditEventService(db_session).record_event(
            audit_context=build_audit_context_from_request(
                actor_user_id=actor.user.id, request=request
            ),
            category=AuditCategory.PLATFORM,
            action=AuditAction.ORGANISATION_UPDATED,
            target_type=AuditTargetType.ORGANISATION,
            target_id=org.id,
            reason=payload.reason,
        )
    await db_session.refresh(org)
    return PlatformOrganisationResponse.model_validate(org)

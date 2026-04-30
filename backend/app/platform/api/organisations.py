from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.requests import Request

from app.audit.context import build_audit_context_from_request
from app.core.db import get_db_session
from app.core.platform import (
    PlatformActor,
    PlatformPermission,
    require_platform_permission,
)
from app.platform.schemas.platform_organisations import (
    PlatformOrganisationPatchRequest,
    PlatformOrganisationResponse,
    PlatformOrganisationsCollectionResponse,
    PlatformOrganisationsMeta,
)
from app.platform.schemas.platform_users import ReasonRequest
from app.platform.services.platform_organisations import PlatformOrganisationsService

router = APIRouter(prefix="/platform/organisations", tags=["platform"])


@router.get("", response_model=PlatformOrganisationsCollectionResponse)
async def list_platform_orgs(
    _: Annotated[
        PlatformActor,
        Depends(require_platform_permission(PlatformPermission.ORGANISATIONS_READ)),
    ],
    db_session: Annotated[AsyncSession, Depends(get_db_session)],
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> PlatformOrganisationsCollectionResponse:
    organisations, total = await PlatformOrganisationsService(
        db_session
    ).list_organisations(limit=limit, offset=offset)
    return PlatformOrganisationsCollectionResponse(
        data=[
            PlatformOrganisationResponse.model_validate(org) for org in organisations
        ],
        meta=PlatformOrganisationsMeta(total=total, limit=limit, offset=offset),
        links={},
    )


@router.get("/{organisation_id}", response_model=PlatformOrganisationResponse)
async def get_platform_org(
    organisation_id: UUID,
    _: Annotated[
        PlatformActor,
        Depends(require_platform_permission(PlatformPermission.ORGANISATIONS_READ)),
    ],
    db_session: Annotated[AsyncSession, Depends(get_db_session)],
) -> PlatformOrganisationResponse:
    org = await PlatformOrganisationsService(db_session).get_organisation(
        organisation_id
    )
    return PlatformOrganisationResponse.model_validate(org)


@router.post("/{organisation_id}/suspend", response_model=PlatformOrganisationResponse)
async def suspend_platform_org(
    organisation_id: UUID,
    payload: ReasonRequest,
    actor: Annotated[
        PlatformActor,
        Depends(require_platform_permission(PlatformPermission.ORGANISATIONS_SUSPEND)),
    ],
    request: Request,
    db_session: Annotated[AsyncSession, Depends(get_db_session)],
) -> PlatformOrganisationResponse:
    org = await PlatformOrganisationsService(db_session).suspend_organisation(
        organisation_id=organisation_id,
        actor=actor,
        reason=payload.reason,
        audit_context=build_audit_context_from_request(
            actor_user_id=actor.user.id, request=request
        ),
    )
    return PlatformOrganisationResponse.model_validate(org)


@router.post("/{organisation_id}/restore", response_model=PlatformOrganisationResponse)
async def restore_platform_org(
    organisation_id: UUID,
    payload: ReasonRequest,
    actor: Annotated[
        PlatformActor,
        Depends(require_platform_permission(PlatformPermission.ORGANISATIONS_RESTORE)),
    ],
    request: Request,
    db_session: Annotated[AsyncSession, Depends(get_db_session)],
) -> PlatformOrganisationResponse:
    org = await PlatformOrganisationsService(db_session).restore_organisation(
        organisation_id=organisation_id,
        actor=actor,
        reason=payload.reason,
        audit_context=build_audit_context_from_request(
            actor_user_id=actor.user.id, request=request
        ),
    )
    return PlatformOrganisationResponse.model_validate(org)


@router.patch("/{organisation_id}", response_model=PlatformOrganisationResponse)
async def patch_platform_org(
    organisation_id: UUID,
    payload: PlatformOrganisationPatchRequest,
    actor: Annotated[
        PlatformActor,
        Depends(
            require_platform_permission(
                PlatformPermission.ORGANISATIONS_CORRECT_PROFILE
            )
        ),
    ],
    request: Request,
    db_session: Annotated[AsyncSession, Depends(get_db_session)],
) -> PlatformOrganisationResponse:
    org = await PlatformOrganisationsService(db_session).correct_organisation_profile(
        organisation_id=organisation_id,
        actor=actor,
        name=payload.name,
        slug=payload.slug,
        reason=payload.reason,
        audit_context=build_audit_context_from_request(
            actor_user_id=actor.user.id, request=request
        ),
    )
    return PlatformOrganisationResponse.model_validate(org)

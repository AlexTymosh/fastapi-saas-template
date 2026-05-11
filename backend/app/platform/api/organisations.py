from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.requests import Request

from app.audit.context import build_audit_context_from_request
from app.core.db import get_db_session
from app.core.errors.openapi import (
    COMMON_ERROR_RESPONSES,
    RATE_LIMIT_ERROR_RESPONSES,
    WRITE_ERROR_RESPONSES,
)
from app.core.platform import (
    PlatformActor,
    PlatformPermission,
    PlatformWriteContext,
    require_any_platform_permission,
    require_platform_permission,
    require_rate_limited_platform_write_context,
)
from app.core.rate_limit import PLATFORM_READ_POLICY, rate_limit_dependency
from app.organisations.models.organisation import OrganisationStatus
from app.platform.schemas.platform_organisations import (
    PlatformLimitedOrganisationResponse,
    PlatformLimitedOrganisationsCollectionResponse,
    PlatformOrganisationPatchRequest,
    PlatformOrganisationResponse,
    PlatformOrganisationsCollectionResponse,
    PlatformOrganisationsMeta,
)
from app.platform.schemas.platform_users import ReasonRequest
from app.platform.services.platform_organisations import PlatformOrganisationsService

router = APIRouter(prefix="/platform/organisations", tags=["platform-organisations"])


@router.get(
    "/limited",
    response_model=PlatformLimitedOrganisationsCollectionResponse,
    responses={**COMMON_ERROR_RESPONSES, **RATE_LIMIT_ERROR_RESPONSES},
    operation_id="list_limited_platform_organisations",
)
async def list_limited_platform_orgs(
    _rate_limit: Annotated[None, Depends(rate_limit_dependency(PLATFORM_READ_POLICY))],
    _: Annotated[
        PlatformActor,
        Depends(
            require_any_platform_permission(
                PlatformPermission.ORGANISATIONS_READ_LIMITED,
                PlatformPermission.ORGANISATIONS_READ,
            )
        ),
    ],
    db_session: Annotated[AsyncSession, Depends(get_db_session)],
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    status: OrganisationStatus | None = None,
    q: str | None = Query(default=None, min_length=1, max_length=255),
) -> PlatformLimitedOrganisationsCollectionResponse:
    organisations, total = await PlatformOrganisationsService(
        db_session
    ).list_limited_organisations(
        limit=limit,
        offset=offset,
        status=status,
        q=q,
    )
    return PlatformLimitedOrganisationsCollectionResponse(
        data=[
            PlatformLimitedOrganisationResponse.model_validate(org)
            for org in organisations
        ],
        meta=PlatformOrganisationsMeta(total=total, limit=limit, offset=offset),
        links={},
    )


@router.get(
    "",
    response_model=PlatformOrganisationsCollectionResponse,
    responses={**COMMON_ERROR_RESPONSES, **RATE_LIMIT_ERROR_RESPONSES},
    operation_id="list_platform_organisations",
)
async def list_platform_orgs(
    _rate_limit: Annotated[None, Depends(rate_limit_dependency(PLATFORM_READ_POLICY))],
    _: Annotated[
        PlatformActor,
        Depends(require_platform_permission(PlatformPermission.ORGANISATIONS_READ)),
    ],
    db_session: Annotated[AsyncSession, Depends(get_db_session)],
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    status: OrganisationStatus | None = None,
    q: str | None = Query(default=None, min_length=1, max_length=255),
) -> PlatformOrganisationsCollectionResponse:
    organisations, total = await PlatformOrganisationsService(
        db_session
    ).list_organisations(limit=limit, offset=offset, status=status, q=q)
    return PlatformOrganisationsCollectionResponse(
        data=[
            PlatformOrganisationResponse.model_validate(org) for org in organisations
        ],
        meta=PlatformOrganisationsMeta(total=total, limit=limit, offset=offset),
        links={},
    )


@router.get(
    "/{organisation_id}",
    response_model=PlatformOrganisationResponse,
    responses={**COMMON_ERROR_RESPONSES, **RATE_LIMIT_ERROR_RESPONSES},
    operation_id="get_platform_organisation",
)
async def get_platform_org(
    organisation_id: UUID,
    _rate_limit: Annotated[None, Depends(rate_limit_dependency(PLATFORM_READ_POLICY))],
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


@router.post(
    "/{organisation_id}/suspend",
    response_model=PlatformOrganisationResponse,
    status_code=status.HTTP_200_OK,
    responses={**WRITE_ERROR_RESPONSES, **RATE_LIMIT_ERROR_RESPONSES},
    operation_id="suspend_platform_organisation",
)
async def suspend_platform_org(
    organisation_id: UUID,
    payload: ReasonRequest,
    write_context: Annotated[
        PlatformWriteContext,
        Depends(
            require_rate_limited_platform_write_context(
                PlatformPermission.ORGANISATIONS_SUSPEND
            ),
            scope="function",
        ),
    ],
    request: Request,
) -> PlatformOrganisationResponse:
    actor = write_context.actor
    org = await PlatformOrganisationsService(
        write_context.session
    ).suspend_organisation(
        organisation_id=organisation_id,
        actor=actor,
        reason=payload.reason,
        audit_context=build_audit_context_from_request(
            actor_user_id=actor.user.id, request=request
        ),
    )
    return PlatformOrganisationResponse.model_validate(org)


@router.post(
    "/{organisation_id}/restore",
    response_model=PlatformOrganisationResponse,
    status_code=status.HTTP_200_OK,
    responses={**WRITE_ERROR_RESPONSES, **RATE_LIMIT_ERROR_RESPONSES},
    operation_id="restore_platform_organisation",
)
async def restore_platform_org(
    organisation_id: UUID,
    payload: ReasonRequest,
    write_context: Annotated[
        PlatformWriteContext,
        Depends(
            require_rate_limited_platform_write_context(
                PlatformPermission.ORGANISATIONS_RESTORE
            ),
            scope="function",
        ),
    ],
    request: Request,
) -> PlatformOrganisationResponse:
    actor = write_context.actor
    org = await PlatformOrganisationsService(
        write_context.session
    ).restore_organisation(
        organisation_id=organisation_id,
        actor=actor,
        reason=payload.reason,
        audit_context=build_audit_context_from_request(
            actor_user_id=actor.user.id, request=request
        ),
    )
    return PlatformOrganisationResponse.model_validate(org)


@router.patch(
    "/{organisation_id}",
    response_model=PlatformOrganisationResponse,
    responses={**WRITE_ERROR_RESPONSES, **RATE_LIMIT_ERROR_RESPONSES},
    operation_id="patch_platform_organisation",
)
async def patch_platform_org(
    organisation_id: UUID,
    payload: PlatformOrganisationPatchRequest,
    write_context: Annotated[
        PlatformWriteContext,
        Depends(
            require_rate_limited_platform_write_context(
                PlatformPermission.ORGANISATIONS_CORRECT_PROFILE
            ),
            scope="function",
        ),
    ],
    request: Request,
) -> PlatformOrganisationResponse:
    actor = write_context.actor
    org = await PlatformOrganisationsService(
        write_context.session
    ).correct_organisation_profile(
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

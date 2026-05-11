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
    require_platform_permission,
    require_rate_limited_platform_write_context,
)
from app.core.rate_limit import PLATFORM_READ_POLICY, rate_limit_dependency
from app.platform.schemas.platform_organisations import (
    PlatformLimitedOrganisationResponse,
    PlatformLimitedOrganisationsCollectionResponse,
    PlatformOrganisationPatchRequest,
    PlatformOrganisationResponse,
    PlatformOrganisationsCollectionResponse,
    PlatformOrganisationsMeta,
)
from app.platform.schemas.platform_query import (
    PlatformLimitedOrganisationListQuery,
    PlatformOrganisationListQuery,
)
from app.platform.schemas.platform_users import ReasonRequest
from app.platform.services.platform_organisations import PlatformOrganisationsService

router = APIRouter(prefix="/platform/organisations", tags=["platform-organisations"])


@router.get(
    "/limited",
    response_model=PlatformLimitedOrganisationsCollectionResponse,
    responses={**COMMON_ERROR_RESPONSES, **RATE_LIMIT_ERROR_RESPONSES},
)
async def list_limited_platform_organisations(
    _rate_limit: Annotated[None, Depends(rate_limit_dependency(PLATFORM_READ_POLICY))],
    _: Annotated[
        PlatformActor,
        Depends(
            require_platform_permission(PlatformPermission.ORGANISATIONS_READ_LIMITED)
        ),
    ],
    db_session: Annotated[AsyncSession, Depends(get_db_session)],
    query: Annotated[PlatformLimitedOrganisationListQuery, Query()],
) -> PlatformLimitedOrganisationsCollectionResponse:
    organisations, total = await PlatformOrganisationsService(
        db_session
    ).list_limited_organisations(
        limit=query.limit,
        offset=query.offset,
        status=query.status,
        q=query.q,
    )
    return PlatformLimitedOrganisationsCollectionResponse(
        data=[
            PlatformLimitedOrganisationResponse.model_validate(org)
            for org in organisations
        ],
        meta=PlatformOrganisationsMeta(
            total=total, limit=query.limit, offset=query.offset
        ),
        links={},
    )


@router.get(
    "",
    response_model=PlatformOrganisationsCollectionResponse,
    responses={**COMMON_ERROR_RESPONSES, **RATE_LIMIT_ERROR_RESPONSES},
)
async def list_platform_organisations(
    _rate_limit: Annotated[None, Depends(rate_limit_dependency(PLATFORM_READ_POLICY))],
    _: Annotated[
        PlatformActor,
        Depends(require_platform_permission(PlatformPermission.ORGANISATIONS_READ)),
    ],
    db_session: Annotated[AsyncSession, Depends(get_db_session)],
    query: Annotated[PlatformOrganisationListQuery, Query()],
) -> PlatformOrganisationsCollectionResponse:
    organisations, total = await PlatformOrganisationsService(
        db_session
    ).list_organisations(
        limit=query.limit, offset=query.offset, status=query.status, q=query.q
    )
    return PlatformOrganisationsCollectionResponse(
        data=[
            PlatformOrganisationResponse.model_validate(org) for org in organisations
        ],
        meta=PlatformOrganisationsMeta(
            total=total, limit=query.limit, offset=query.offset
        ),
        links={},
    )


@router.get(
    "/{organisation_id}",
    response_model=PlatformOrganisationResponse,
    responses={**COMMON_ERROR_RESPONSES, **RATE_LIMIT_ERROR_RESPONSES},
)
async def get_platform_organisation(
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
)
async def suspend_platform_organisation(
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
)
async def restore_platform_organisation(
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
)
async def patch_platform_organisation(
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

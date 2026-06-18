from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query
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
    PlatformPermission,
    PlatformWriteContext,
    require_platform_permission,
    require_rate_limited_platform_write_context,
)
from app.core.rate_limit import (
    PLATFORM_READ_POLICY,
    PRIVACY_EXPORT_DOWNLOAD_URL_POLICY,
    rate_limit_dependency,
)
from app.privacy.rate_limits import check_export_artifact_download_url_rate_limit
from app.privacy.schemas.export_artifacts import (
    ExportArtifactResponse,
    ExportArtifactsCollectionResponse,
    ExportArtifactsMeta,
    ExportDownloadUrlResponse,
)
from app.privacy.services.export_artifacts import ExportArtifactService

router = APIRouter(prefix="/platform/privacy", tags=["platform-privacy"])


@router.post(
    "/data-subject-requests/{request_id}/export-artifact",
    response_model=ExportArtifactResponse,
    responses={**WRITE_ERROR_RESPONSES, **RATE_LIMIT_ERROR_RESPONSES},
)
async def create_platform_export_artifact(
    request_id: UUID,
    request: Request,
    write_context: Annotated[
        PlatformWriteContext,
        Depends(
            require_rate_limited_platform_write_context(PlatformPermission.GDPR_EXPORT),
            scope="function",
        ),
    ],
) -> ExportArtifactResponse:
    actor = write_context.actor
    row = await ExportArtifactService(write_context.session).request_export_artifact(
        request_id=request_id,
        requested_by_user_id=actor.user.id,
        audit_context=build_audit_context_from_request(
            actor_user_id=actor.user.id, request=request
        ),
    )
    return ExportArtifactResponse.model_validate(row)


@router.get(
    "/export-artifacts",
    response_model=ExportArtifactsCollectionResponse,
    responses={**COMMON_ERROR_RESPONSES, **RATE_LIMIT_ERROR_RESPONSES},
)
async def list_platform_export_artifacts(
    _rate_limit: Annotated[None, Depends(rate_limit_dependency(PLATFORM_READ_POLICY))],
    _: Annotated[
        object,
        Depends(
            require_platform_permission(
                PlatformPermission.PRIVACY_EXPORT_ARTIFACTS_READ
            )
        ),
    ],
    db_session: Annotated[AsyncSession, Depends(get_db_session)],
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> ExportArtifactsCollectionResponse:
    rows, total = await ExportArtifactService(
        db_session
    ).list_platform_export_artifacts(limit=limit, offset=offset)
    return ExportArtifactsCollectionResponse(
        data=[ExportArtifactResponse.model_validate(row) for row in rows],
        meta=ExportArtifactsMeta(total=total, limit=limit, offset=offset),
        links={},
    )


@router.get(
    "/export-artifacts/{artifact_id}",
    response_model=ExportArtifactResponse,
    responses={**COMMON_ERROR_RESPONSES, **RATE_LIMIT_ERROR_RESPONSES},
)
async def get_platform_export_artifact(
    artifact_id: UUID,
    _rate_limit: Annotated[None, Depends(rate_limit_dependency(PLATFORM_READ_POLICY))],
    _: Annotated[
        object,
        Depends(
            require_platform_permission(
                PlatformPermission.PRIVACY_EXPORT_ARTIFACTS_READ
            )
        ),
    ],
    db_session: Annotated[AsyncSession, Depends(get_db_session)],
) -> ExportArtifactResponse:
    row = await ExportArtifactService(db_session).get_platform_export_artifact(
        artifact_id=artifact_id
    )
    return ExportArtifactResponse.model_validate(row)


@router.post(
    "/export-artifacts/{artifact_id}/download-url",
    response_model=ExportDownloadUrlResponse,
    responses={**WRITE_ERROR_RESPONSES, **RATE_LIMIT_ERROR_RESPONSES},
)
async def create_platform_export_download_url(
    artifact_id: UUID,
    request: Request,
    write_context: Annotated[
        PlatformWriteContext,
        Depends(
            require_rate_limited_platform_write_context(
                PlatformPermission.GDPR_EXPORT,
                policy=PRIVACY_EXPORT_DOWNLOAD_URL_POLICY,
            ),
            scope="function",
        ),
    ],
) -> ExportDownloadUrlResponse:
    actor = write_context.actor
    service = ExportArtifactService(write_context.session)
    artifact = await service.get_platform_export_artifact(artifact_id=artifact_id)
    await check_export_artifact_download_url_rate_limit(
        request=request,
        artifact_id=artifact.id,
    )
    download = await service.generate_download_url(
        artifact=artifact,
        audit_context=build_audit_context_from_request(
            actor_user_id=actor.user.id, request=request
        ),
    )
    return ExportDownloadUrlResponse(
        url=download.url,
        expires_in_seconds=download.expires_in_seconds,
    )

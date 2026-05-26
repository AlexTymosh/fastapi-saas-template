from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.requests import Request

from app.audit.context import build_audit_context_from_request
from app.core.auth import AuthenticatedPrincipal, require_authenticated_principal
from app.core.db import get_db_session
from app.core.errors.openapi import (
    COMMON_ERROR_RESPONSES,
    RATE_LIMIT_ERROR_RESPONSES,
    WRITE_ERROR_RESPONSES,
)
from app.core.rate_limit import TENANT_READ_POLICY, rate_limit_dependency
from app.privacy.schemas.export_artifacts import (
    ExportArtifactResponse,
    ExportArtifactsCollectionResponse,
    ExportArtifactsMeta,
    ExportDownloadUrlResponse,
)
from app.privacy.services.export_artifacts import ExportArtifactService
from app.users.models.user import User
from app.users.services.users import UserService

router = APIRouter(prefix="/privacy/export-artifacts", tags=["privacy"])


async def _provision_current_user(
    *, db_session: AsyncSession, identity: AuthenticatedPrincipal
) -> User:
    """Return a local user projection for self-service export artifact routes.

    Authenticated first-time users may not yet have a local projection row. Using
    JIT provisioning here avoids turning valid authenticated requests into 500s
    when the route later needs user.id for ownership checks.
    """
    return await UserService(db_session).provision_current_user(identity)


@router.get(
    "",
    response_model=ExportArtifactsCollectionResponse,
    responses={**COMMON_ERROR_RESPONSES, **RATE_LIMIT_ERROR_RESPONSES},
)
async def list_own_export_artifacts(
    identity: Annotated[
        AuthenticatedPrincipal, Depends(require_authenticated_principal)
    ],
    _rate_limit: Annotated[None, Depends(rate_limit_dependency(TENANT_READ_POLICY))],
    db_session: Annotated[AsyncSession, Depends(get_db_session)],
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> ExportArtifactsCollectionResponse:
    user = await _provision_current_user(db_session=db_session, identity=identity)
    rows, total = await ExportArtifactService(db_session).list_own_export_artifacts(
        requester_user_id=user.id, limit=limit, offset=offset
    )
    return ExportArtifactsCollectionResponse(
        data=[ExportArtifactResponse.model_validate(row) for row in rows],
        meta=ExportArtifactsMeta(total=total, limit=limit, offset=offset),
        links={},
    )


@router.get(
    "/{artifact_id}",
    response_model=ExportArtifactResponse,
    responses={**COMMON_ERROR_RESPONSES, **RATE_LIMIT_ERROR_RESPONSES},
)
async def get_own_export_artifact(
    artifact_id: UUID,
    identity: Annotated[
        AuthenticatedPrincipal, Depends(require_authenticated_principal)
    ],
    _rate_limit: Annotated[None, Depends(rate_limit_dependency(TENANT_READ_POLICY))],
    db_session: Annotated[AsyncSession, Depends(get_db_session)],
) -> ExportArtifactResponse:
    user = await _provision_current_user(db_session=db_session, identity=identity)
    row = await ExportArtifactService(db_session).get_own_export_artifact(
        artifact_id=artifact_id, requester_user_id=user.id
    )
    return ExportArtifactResponse.model_validate(row)


@router.post(
    "/{artifact_id}/download-url",
    response_model=ExportDownloadUrlResponse,
    responses={**WRITE_ERROR_RESPONSES, **RATE_LIMIT_ERROR_RESPONSES},
)
async def create_own_export_download_url(
    artifact_id: UUID,
    request: Request,
    identity: Annotated[
        AuthenticatedPrincipal, Depends(require_authenticated_principal)
    ],
    _rate_limit: Annotated[None, Depends(rate_limit_dependency(TENANT_READ_POLICY))],
    db_session: Annotated[AsyncSession, Depends(get_db_session)],
) -> ExportDownloadUrlResponse:
    async with db_session.begin():
        user = await _provision_current_user(db_session=db_session, identity=identity)
        service = ExportArtifactService(db_session)
        artifact = await service.get_own_export_artifact(
            artifact_id=artifact_id, requester_user_id=user.id
        )
        download = await service.generate_download_url(
            artifact=artifact,
            audit_context=build_audit_context_from_request(
                actor_user_id=user.id, request=request
            ),
        )
    return ExportDownloadUrlResponse(
        url=download.url,
        expires_in_seconds=download.expires_in_seconds,
    )

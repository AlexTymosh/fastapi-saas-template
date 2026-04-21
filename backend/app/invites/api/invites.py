from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import AuthenticatedPrincipal, require_authenticated_principal
from app.core.db import get_db_session
from app.core.errors.openapi import COMMON_ERROR_RESPONSES, WRITE_ERROR_RESPONSES
from app.invites.schemas.invites import AcceptInviteResponse, CreateInviteRequest, InviteResponse
from app.invites.services.invites import InviteService

router = APIRouter(tags=["invites"])
DbSessionDep = Annotated[AsyncSession, Depends(get_db_session)]


@router.post(
    "/organisations/{organisation_id}/invites",
    response_model=InviteResponse,
    status_code=status.HTTP_201_CREATED,
    responses=WRITE_ERROR_RESPONSES,
)
async def create_invite(
    organisation_id: UUID,
    payload: CreateInviteRequest,
    identity: Annotated[AuthenticatedPrincipal, Depends(require_authenticated_principal)],
    db_session: DbSessionDep,
) -> InviteResponse:
    service = InviteService(db_session)
    invite = await service.create_invite(
        identity=identity,
        organisation_id=organisation_id,
        email=str(payload.email),
        role=payload.role,
    )
    return InviteResponse.model_validate(invite)


@router.post(
    "/invites/{token}/accept",
    response_model=AcceptInviteResponse,
    responses=COMMON_ERROR_RESPONSES,
)
async def accept_invite(
    token: str,
    identity: Annotated[AuthenticatedPrincipal, Depends(require_authenticated_principal)],
    db_session: DbSessionDep,
) -> AcceptInviteResponse:
    service = InviteService(db_session)
    invite = await service.accept_invite(identity=identity, token=token)
    return AcceptInviteResponse(invite=InviteResponse.model_validate(invite))

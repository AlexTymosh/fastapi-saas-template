from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import AuthenticatedPrincipal, require_authenticated_principal
from app.core.db import get_db_session
from app.core.errors.openapi import COMMON_ERROR_RESPONSES, WRITE_ERROR_RESPONSES
from app.invites.schemas.invites import (
    AcceptInviteResponse,
    CreateInviteRequest,
    InviteCreateResponse,
    InviteResponse,
)
from app.invites.services.invites import InviteService
from app.users.services.users import UserService

router = APIRouter(tags=["invites"])
DbSessionDep = Annotated[AsyncSession, Depends(get_db_session)]
PrincipalDep = Annotated[
    AuthenticatedPrincipal,
    Depends(require_authenticated_principal),
]


@router.post(
    "/organisations/{organisation_id}/invites",
    response_model=InviteCreateResponse,
    status_code=status.HTTP_201_CREATED,
    responses=WRITE_ERROR_RESPONSES,
    name="create_organisation_invite",
)
async def create_invite(
    organisation_id: UUID,
    payload: CreateInviteRequest,
    identity: PrincipalDep,
    db_session: DbSessionDep,
) -> InviteCreateResponse:
    user = await UserService(db_session).provision_current_user(identity)
    invite_service = InviteService(db_session)
    invite, _token = await invite_service.create_invite(
        organisation_id=organisation_id,
        actor_user_id=user.id,
        role=payload.role,
        email=payload.email,
        actor_is_superadmin=identity.is_superadmin(),
    )
    invite_payload = InviteResponse.model_validate(invite)
    return InviteCreateResponse(invite=invite_payload)


@router.post(
    "/invites/{token}/accept",
    response_model=AcceptInviteResponse,
    responses=COMMON_ERROR_RESPONSES,
    name="accept_invite",
)
async def accept_invite(
    token: str,
    identity: PrincipalDep,
    db_session: DbSessionDep,
) -> AcceptInviteResponse:
    invite_service = InviteService(db_session)
    membership = await invite_service.accept_invite(token=token, identity=identity)
    return AcceptInviteResponse(
        membership_id=membership.id,
        organisation_id=membership.organisation_id,
        role=membership.role,
    )

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import AuthenticatedPrincipal, require_authenticated_principal
from app.core.db import get_db_session
from app.core.errors.openapi import (
    COMMON_ERROR_RESPONSES,
    RATE_LIMIT_ERROR_RESPONSES,
    WRITE_ERROR_RESPONSES,
)
from app.core.rate_limit import (
    INVITE_ACCEPT_POLICY,
    INVITE_CREATE_POLICY,
    rate_limit_dependency,
)
from app.invites.schemas.invites import (
    AcceptInviteRequest,
    AcceptInviteResponse,
    CreateInviteRequest,
    InviteResponse,
)
from app.invites.services.delivery import InviteTokenSink, get_invite_token_sink
from app.invites.services.invites import InviteService
from app.users.services.users import UserService

router = APIRouter(tags=["invites"])
DbSessionDep = Annotated[AsyncSession, Depends(get_db_session)]
PrincipalDep = Annotated[
    AuthenticatedPrincipal,
    Depends(require_authenticated_principal),
]
InviteTokenSinkDep = Annotated[InviteTokenSink, Depends(get_invite_token_sink)]
InviteAcceptRateLimitDep = Annotated[
    None,
    Depends(rate_limit_dependency(INVITE_ACCEPT_POLICY)),
]
InviteCreateRateLimitDep = Annotated[
    None,
    Depends(rate_limit_dependency(INVITE_CREATE_POLICY)),
]


@router.post(
    "/organisations/{organisation_id}/invites",
    response_model=InviteResponse,
    status_code=status.HTTP_201_CREATED,
    responses={**WRITE_ERROR_RESPONSES, **RATE_LIMIT_ERROR_RESPONSES},
    name="create_organisation_invite",
)
async def create_invite(
    organisation_id: UUID,
    payload: CreateInviteRequest,
    identity: PrincipalDep,
    db_session: DbSessionDep,
    token_sink: InviteTokenSinkDep,
    _: InviteCreateRateLimitDep,
) -> InviteResponse:
    user = await UserService(db_session).provision_current_user(identity)
    invite_service = InviteService(db_session, token_sink=token_sink)
    invite = await invite_service.create_invite(
        organisation_id=organisation_id,
        actor_user_id=user.id,
        role=payload.role,
        email=payload.email,
        actor_is_superadmin=identity.is_superadmin(),
    )
    return InviteResponse.model_validate(invite)


@router.post(
    "/invites/accept",
    response_model=AcceptInviteResponse,
    responses={**COMMON_ERROR_RESPONSES, **RATE_LIMIT_ERROR_RESPONSES},
    name="accept_invite",
)
async def accept_invite(
    payload: AcceptInviteRequest,
    identity: PrincipalDep,
    db_session: DbSessionDep,
    _: InviteAcceptRateLimitDep,
) -> AcceptInviteResponse:
    invite_service = InviteService(db_session)
    membership = await invite_service.accept_invite(
        token=payload.token,
        identity=identity,
    )
    return AcceptInviteResponse(
        membership_id=membership.id,
        organisation_id=membership.organisation_id,
        role=membership.role,
    )

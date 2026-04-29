from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import AuthenticatedPrincipal, require_authenticated_principal
from app.core.db import get_db_session
from app.core.errors.openapi import COMMON_ERROR_RESPONSES
from app.memberships.services.memberships import MembershipService
from app.users.schemas.users import MembershipSummary, UserMeResponse
from app.users.services.users import UserService

router = APIRouter(prefix="/users", tags=["users"])

DbSessionDep = Annotated[AsyncSession, Depends(get_db_session)]


@router.get(
    "/me",
    response_model=UserMeResponse,
    responses=COMMON_ERROR_RESPONSES,
    name="get_me",
)
async def get_me(
    identity: Annotated[
        AuthenticatedPrincipal,
        Depends(require_authenticated_principal),
    ],
    db_session: DbSessionDep,
) -> UserMeResponse:
    user_service = UserService(db_session)
    membership_service = MembershipService(db_session)

    user = await user_service.get_me(identity)
    membership = await membership_service.get_membership_for_user(user.id)

    return UserMeResponse(
        id=user.id,
        external_auth_id=user.external_auth_id,
        email=user.email,
        email_verified=user.email_verified,
        first_name=user.first_name,
        last_name=user.last_name,
        onboarding_completed=user.onboarding_completed,
        status=user.status,
        membership=(
            MembershipSummary(
                organisation_id=membership.organisation_id,
                role=membership.role,
            )
            if membership is not None
            else None
        ),
        created_at=user.created_at,
        updated_at=user.updated_at,
    )

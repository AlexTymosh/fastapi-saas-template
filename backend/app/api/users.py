from typing import Annotated

from fastapi import APIRouter, Depends

from app.api.dependencies.domain_services import get_user_service
from app.core.auth import (
    AuthenticatedIdentity,
    get_current_authenticated_identity,
)
from app.core.errors.openapi import COMMON_ERROR_RESPONSES
from app.users.schemas.user import MeResponse
from app.users.services.user_service import UserService

router = APIRouter(tags=["users"])


@router.get(
    "/users/me",
    response_model=MeResponse,
    responses=COMMON_ERROR_RESPONSES,
    name="users_me",
)
async def get_me(
    identity: Annotated[
        AuthenticatedIdentity,
        Depends(get_current_authenticated_identity),
    ],
    user_service: Annotated[UserService, Depends(get_user_service)],
) -> MeResponse:
    user, has_any_organisation = await user_service.get_me(identity)
    return MeResponse(
        id=user.id,
        external_auth_id=user.external_auth_id,
        email=user.email,
        email_verified=user.email_verified,
        first_name=user.first_name,
        last_name=user.last_name,
        onboarding_completed=user.onboarding_completed,
        has_any_organisation=has_any_organisation,
    )

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from app.core.errors.openapi import COMMON_ERROR_RESPONSES, RATE_LIMIT_ERROR_RESPONSES
from app.core.platform import PlatformActor, require_platform_actor
from app.core.rate_limit import PLATFORM_READ_POLICY, rate_limit_dependency
from app.platform.schemas.platform_identity import PlatformIdentityResponse

router = APIRouter(prefix="/platform", tags=["platform-identity"])


@router.get(
    "/me",
    response_model=PlatformIdentityResponse,
    responses={**COMMON_ERROR_RESPONSES, **RATE_LIMIT_ERROR_RESPONSES},
)
async def get_platform_identity(
    _rate_limit: Annotated[None, Depends(rate_limit_dependency(PLATFORM_READ_POLICY))],
    actor: Annotated[PlatformActor, Depends(require_platform_actor())],
) -> PlatformIdentityResponse:
    return PlatformIdentityResponse.from_actor(actor)

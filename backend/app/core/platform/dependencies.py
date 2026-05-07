from __future__ import annotations

from collections.abc import Callable
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import AuthenticatedPrincipal, require_authenticated_principal
from app.core.db import get_db_session
from app.core.platform.actors import PlatformActor
from app.core.platform.permissions import PlatformPermission
from app.core.platform.write_context import resolve_platform_actor
from app.core.rate_limit import PLATFORM_READ_POLICY, RateLimitPolicy, check_rate_limit


def require_platform_permission(
    permission: PlatformPermission,
) -> Callable[..., PlatformActor]:
    async def dependency(
        identity: Annotated[
            AuthenticatedPrincipal, Depends(require_authenticated_principal)
        ],
        db_session: Annotated[AsyncSession, Depends(get_db_session)],
    ) -> PlatformActor:
        return await resolve_platform_actor(
            identity=identity,
            session=db_session,
            required_permission=permission,
        )

    return dependency


def require_rate_limited_platform_permission(
    permission: PlatformPermission,
    *,
    policy: RateLimitPolicy = PLATFORM_READ_POLICY,
) -> Callable[..., PlatformActor]:
    async def dependency(
        request: Request,
        identity: Annotated[
            AuthenticatedPrincipal, Depends(require_authenticated_principal)
        ],
        db_session: Annotated[AsyncSession, Depends(get_db_session)],
    ) -> PlatformActor:
        await check_rate_limit(request=request, principal=identity, policy=policy)
        return await resolve_platform_actor(
            identity=identity,
            session=db_session,
            required_permission=permission,
        )

    dependency.__rate_limit_policy_name__ = policy.name  # type: ignore[attr-defined]
    dependency.__rate_limit_policy__ = policy  # type: ignore[attr-defined]
    return dependency

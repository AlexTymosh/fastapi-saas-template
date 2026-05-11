from __future__ import annotations

from collections.abc import Callable
from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import AuthenticatedPrincipal, require_authenticated_principal
from app.core.db import get_db_session
from app.core.platform.actors import PlatformActor
from app.core.platform.permissions import PlatformPermission
from app.core.platform.write_context import (
    ensure_platform_permission,
    resolve_active_platform_actor,
)


def require_platform_permission(
    permission: PlatformPermission,
) -> Callable[..., PlatformActor]:
    async def dependency(
        identity: Annotated[
            AuthenticatedPrincipal, Depends(require_authenticated_principal)
        ],
        db_session: Annotated[AsyncSession, Depends(get_db_session)],
    ) -> PlatformActor:
        actor = await resolve_active_platform_actor(
            identity=identity,
            session=db_session,
        )
        return ensure_platform_permission(actor=actor, required_permission=permission)

    return dependency


async def require_platform_actor(
    identity: Annotated[
        AuthenticatedPrincipal, Depends(require_authenticated_principal)
    ],
    db_session: Annotated[AsyncSession, Depends(get_db_session)],
) -> PlatformActor:
    return await resolve_active_platform_actor(
        identity=identity,
        session=db_session,
    )

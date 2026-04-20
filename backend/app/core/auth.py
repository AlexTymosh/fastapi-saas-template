from __future__ import annotations

from fastapi import Depends, Request
from pydantic import BaseModel, ConfigDict, Field

from app.core.errors.exceptions import UnauthorizedError


class AuthenticatedIdentity(BaseModel):
    model_config = ConfigDict(extra="ignore")

    sub: str = Field(min_length=1)
    email: str | None = None
    email_verified: bool = False
    first_name: str | None = None
    last_name: str | None = None


async def get_current_identity(request: Request) -> AuthenticatedIdentity:
    """Placeholder dependency for JWT-authenticated identity from Keycloak."""
    identity = getattr(request.state, "authenticated_identity", None)
    if identity is None:
        raise UnauthorizedError(detail="Authentication required")

    if isinstance(identity, AuthenticatedIdentity):
        return identity

    if isinstance(identity, dict):
        return AuthenticatedIdentity.model_validate(identity)

    raise UnauthorizedError(detail="Invalid authentication context")


CurrentIdentity = Depends(get_current_identity)

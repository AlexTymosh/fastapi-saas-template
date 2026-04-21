from __future__ import annotations

from typing import Annotated

from fastapi import Depends
from pydantic import BaseModel, ConfigDict, Field

from app.core.errors.exceptions import UnauthorizedError


class AuthenticatedIdentity(BaseModel):
    model_config = ConfigDict(extra="ignore")

    sub: str = Field(min_length=1)
    email: str | None = None
    email_verified: bool = False
    first_name: str | None = None
    last_name: str | None = None


async def get_authenticated_identity() -> AuthenticatedIdentity | None:
    """Authentication provider placeholder for future Keycloak/JWT integration."""
    return None


IdentityProviderDep = Annotated[
    AuthenticatedIdentity | None,
    Depends(get_authenticated_identity),
]


async def get_current_identity(
    authenticated_identity: IdentityProviderDep,
) -> AuthenticatedIdentity:
    if authenticated_identity is None:
        raise UnauthorizedError(detail="Authentication required")

    return authenticated_identity


CurrentIdentity = Depends(get_current_identity)

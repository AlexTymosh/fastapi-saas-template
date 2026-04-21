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


async def get_authenticated_identity() -> AuthenticatedIdentity:
    """Production auth provider placeholder until JWT verification is integrated."""
    raise UnauthorizedError(detail="Authentication required")


async def get_current_identity(
    identity: Annotated[AuthenticatedIdentity, Depends(get_authenticated_identity)],
) -> AuthenticatedIdentity:
    """Resolve the current authenticated identity from the configured provider."""
    return identity


CurrentIdentity = Depends(get_current_identity)

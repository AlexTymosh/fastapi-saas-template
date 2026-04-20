from __future__ import annotations

from fastapi import Header
from pydantic import BaseModel, ConfigDict

from app.core.errors.exceptions import UnauthorizedError


class AuthenticatedIdentity(BaseModel):
    model_config = ConfigDict(extra="ignore")

    sub: str
    email: str | None = None
    email_verified: bool = False
    given_name: str | None = None
    family_name: str | None = None


async def get_current_authenticated_identity(
    x_auth_sub: str | None = Header(default=None),
    x_auth_email: str | None = Header(default=None),
    x_auth_email_verified: str | None = Header(default=None),
    x_auth_given_name: str | None = Header(default=None),
    x_auth_family_name: str | None = Header(default=None),
) -> AuthenticatedIdentity:
    if not x_auth_sub:
        raise UnauthorizedError(detail="Authentication required.")

    return AuthenticatedIdentity(
        sub=x_auth_sub,
        email=x_auth_email,
        email_verified=(x_auth_email_verified or "").lower() == "true",
        given_name=x_auth_given_name,
        family_name=x_auth_family_name,
    )

from __future__ import annotations

from typing import Annotated

from fastapi import Depends
from pydantic import AliasChoices, BaseModel, ConfigDict, Field

from app.core.errors.exceptions import UnauthorizedError


class AuthenticatedPrincipal(BaseModel):
    """Authenticated user projection contract used by application services.

    JWT claim mapping contract (for future JWKS/JWT validation integration):
    - `sub` -> `external_auth_id`
    - `email` -> `email`
    - `email_verified` -> `email_verified`
    - `given_name` or `first_name` -> `first_name`
    - `family_name` or `last_name` -> `last_name`
    """

    model_config = ConfigDict(extra="ignore")

    external_auth_id: str = Field(min_length=1, validation_alias="sub")
    email: str | None = None
    email_verified: bool = False
    first_name: str | None = Field(
        default=None,
        validation_alias=AliasChoices("given_name", "first_name"),
    )
    last_name: str | None = Field(
        default=None,
        validation_alias=AliasChoices("family_name", "last_name"),
    )


async def extract_authenticated_principal() -> AuthenticatedPrincipal:
    """Authentication provider placeholder until JWT/JWKS token validation is wired."""
    raise UnauthorizedError(detail="Authentication required")


async def require_authenticated_principal(
    principal: Annotated[
        AuthenticatedPrincipal,
        Depends(extract_authenticated_principal),
    ],
) -> AuthenticatedPrincipal:
    """Auth boundary dependency consumed by routers and use-cases."""
    return principal


CurrentPrincipal = Annotated[
    AuthenticatedPrincipal,
    Depends(require_authenticated_principal),
]

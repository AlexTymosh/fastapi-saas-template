from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Request
from pydantic import AliasChoices, BaseModel, ConfigDict, EmailStr, Field

from app.core.errors.exceptions import UnauthorizedError


class AuthenticatedPrincipal(BaseModel):
    """
    Auth boundary contract passed to application services.

    JWT claims mapping contract (future verified token -> local principal):
    - sub -> external_auth_id
    - email -> email
    - email_verified -> email_verified
    - given_name / first_name -> first_name
    - family_name / last_name -> last_name
    - roles/platform_roles -> platform_roles
    """

    model_config = ConfigDict(extra="ignore")

    external_auth_id: str = Field(min_length=1)
    email: EmailStr | None = None
    email_verified: bool = False
    first_name: str | None = None
    last_name: str | None = None
    platform_roles: list[str] = Field(default_factory=list)

    def is_superadmin(self) -> bool:
        return any(role.lower() == "superadmin" for role in self.platform_roles)

    @classmethod
    def from_unverified_jwt_claims(
        cls, claims: dict[str, object]
    ) -> AuthenticatedPrincipal:
        payload = JwtClaimsPayload.model_validate(claims)
        return payload.to_authenticated_principal()


class JwtClaimsPayload(BaseModel):
    """Canonical JWT claims payload expected from upstream identity provider."""

    model_config = ConfigDict(extra="ignore")

    external_auth_id: str = Field(
        min_length=1,
        validation_alias="sub",
    )
    email: EmailStr | None = None
    email_verified: bool = False
    first_name: str | None = Field(
        default=None,
        validation_alias=AliasChoices("given_name", "first_name"),
    )
    last_name: str | None = Field(
        default=None,
        validation_alias=AliasChoices("family_name", "last_name"),
    )
    platform_roles: list[str] = Field(
        default_factory=list,
        validation_alias=AliasChoices("platform_roles", "roles"),
    )

    def to_authenticated_principal(self) -> AuthenticatedPrincipal:
        return AuthenticatedPrincipal.model_validate(self.model_dump())


async def get_authenticated_principal(
    request: Request,
) -> AuthenticatedPrincipal | None:
    _ = request
    return None


async def require_authenticated_principal(
    principal: Annotated[
        AuthenticatedPrincipal | None,
        Depends(get_authenticated_principal),
    ],
) -> AuthenticatedPrincipal:
    if principal is None:
        raise UnauthorizedError(detail="Authentication required")
    return principal

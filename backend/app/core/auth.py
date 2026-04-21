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
    """

    model_config = ConfigDict(extra="ignore")

    external_auth_id: str = Field(min_length=1)
    email: EmailStr | None = None
    email_verified: bool = False
    first_name: str | None = None
    last_name: str | None = None

    @classmethod
    def from_unverified_jwt_claims(
        cls, claims: dict[str, object]
    ) -> "AuthenticatedPrincipal":
        """
        Placeholder claims mapping for future JWT/JWKS validation integration.

        Validation of token signature/audience/issuer intentionally deferred.
        """
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

    def to_authenticated_principal(self) -> AuthenticatedPrincipal:
        return AuthenticatedPrincipal.model_validate(self.model_dump())


async def get_authenticated_principal(
    request: Request,
) -> AuthenticatedPrincipal | None:
    """
    Extract authenticated principal from request context.

    Current implementation is a placeholder. This is the future plug-in point for:
    - bearer token extraction
    - JWT verification using JWKS
    - claim validation (iss/aud/exp/etc)
    """
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

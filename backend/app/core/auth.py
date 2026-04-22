from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Request
from pydantic import BaseModel, ConfigDict, EmailStr, Field

from app.core.auth_claims import JwtClaimsPayload, extract_platform_roles
from app.core.auth_jwt import get_jwt_validator
from app.core.config.settings import get_settings
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
        return cls.model_validate(payload.model_dump())

    @classmethod
    def from_verified_jwt_claims(
        cls,
        claims: dict[str, object],
        *,
        resource_client_id: str | None,
    ) -> AuthenticatedPrincipal:
        payload = JwtClaimsPayload.model_validate(
            {
                **claims,
                "platform_roles": extract_platform_roles(
                    claims,
                    resource_client_id=resource_client_id,
                ),
            }
        )
        return cls.model_validate(payload.model_dump())


def _extract_bearer_token(request: Request) -> str | None:
    auth_header = request.headers.get("Authorization")
    if auth_header is None:
        return None

    parts = auth_header.strip().split()
    if len(parts) != 2 or parts[0].lower() != "bearer" or not parts[1].strip():
        raise UnauthorizedError(detail="Malformed Authorization header")

    return parts[1].strip()


async def get_authenticated_principal(
    request: Request,
) -> AuthenticatedPrincipal | None:
    token = _extract_bearer_token(request)
    if token is None:
        return None

    settings = get_settings()
    claims = await get_jwt_validator(settings).validate_token(token)

    return AuthenticatedPrincipal.from_verified_jwt_claims(
        claims,
        resource_client_id=settings.auth.client_id,
    )


async def require_authenticated_principal(
    principal: Annotated[
        AuthenticatedPrincipal | None,
        Depends(get_authenticated_principal),
    ],
) -> AuthenticatedPrincipal:
    if principal is None:
        raise UnauthorizedError(detail="Authentication required")
    return principal

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Request

from app.core.auth_claims import AuthenticatedPrincipal, JwtClaimsPayload
from app.core.auth_jwt import JwtValidator, get_jwt_validator
from app.core.config.settings import get_settings
from app.core.errors.exceptions import UnauthorizedError

__all__ = [
    "AuthenticatedPrincipal",
    "JwtClaimsPayload",
    "JwtValidator",
    "get_authenticated_principal",
    "require_authenticated_principal",
]


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

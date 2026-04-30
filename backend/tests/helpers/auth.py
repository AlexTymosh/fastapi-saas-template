from __future__ import annotations

from app.core.auth import AuthenticatedPrincipal


def identity_for(
    external_auth_id: str,
    email: str,
    *,
    email_verified: bool = True,
    roles: list[str] | None = None,
) -> AuthenticatedPrincipal:
    claims: dict[str, object] = {
        "sub": external_auth_id,
        "email": email,
        "email_verified": email_verified,
    }
    if roles is not None:
        claims["roles"] = roles
    return AuthenticatedPrincipal.from_unverified_jwt_claims(claims)

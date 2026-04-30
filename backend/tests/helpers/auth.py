from __future__ import annotations

from dataclasses import dataclass

from fastapi.testclient import TestClient

from app.core.auth import AuthenticatedPrincipal
from app.core.errors.exceptions import UnauthorizedError


class FakeAuthProvider:
    def __init__(self, identity: AuthenticatedPrincipal | None = None) -> None:
        self._identity = identity

    def set_identity(self, identity: AuthenticatedPrincipal | None) -> None:
        self._identity = identity

    async def get_authenticated_principal(
        self,
        request=None,
    ) -> AuthenticatedPrincipal:
        _ = request
        if self._identity is None:
            raise UnauthorizedError(detail="Authentication required")
        return self._identity


@dataclass(frozen=True)
class AuthenticatedClientBundle:
    client: TestClient
    auth_provider: FakeAuthProvider


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

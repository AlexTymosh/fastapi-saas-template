from __future__ import annotations

from app.core.auth import AuthenticatedIdentity
from app.core.errors.exceptions import UnauthorizedError


class TestAuthProvider:
    def __init__(self, identity: AuthenticatedIdentity | None = None) -> None:
        self._identity = identity

    def set_identity(self, identity: AuthenticatedIdentity | None) -> None:
        self._identity = identity

    async def get_authenticated_identity(self) -> AuthenticatedIdentity:
        if self._identity is None:
            raise UnauthorizedError(detail="Authentication required")
        return self._identity

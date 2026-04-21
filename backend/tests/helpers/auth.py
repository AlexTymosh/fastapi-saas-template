from __future__ import annotations

from app.core.auth import AuthenticatedIdentity


class TestAuthProvider:
    def __init__(self, identity: AuthenticatedIdentity | None = None) -> None:
        self._identity = identity

    def set_identity(self, identity: AuthenticatedIdentity | None) -> None:
        self._identity = identity

    async def get_authenticated_identity(self) -> AuthenticatedIdentity | None:
        return self._identity

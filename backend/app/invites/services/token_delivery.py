from __future__ import annotations

from typing import Protocol

from app.invites.models.invite import Invite


class InviteTokenSink(Protocol):
    async def deliver(self, *, invite: Invite, raw_token: str) -> None: ...


class NullInviteTokenSink:
    async def deliver(self, *, invite: Invite, raw_token: str) -> None:
        _ = invite
        _ = raw_token

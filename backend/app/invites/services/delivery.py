from __future__ import annotations

from typing import Protocol

from app.invites.models.invite import Invite


class InviteTokenSink(Protocol):
    async def deliver(self, *, invite: Invite, raw_token: str) -> None:
        """Deliver raw invite token through an out-of-band channel."""


class NoOpInviteTokenSink:
    async def deliver(self, *, invite: Invite, raw_token: str) -> None:
        return None


_DEFAULT_INVITE_TOKEN_SINK = NoOpInviteTokenSink()


def get_invite_token_sink() -> InviteTokenSink:
    return _DEFAULT_INVITE_TOKEN_SINK

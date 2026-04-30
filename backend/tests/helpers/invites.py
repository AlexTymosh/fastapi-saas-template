from __future__ import annotations


class InMemoryInviteTokenSink:
    def __init__(self) -> None:
        self._tokens_by_email: dict[str, str] = {}

    async def deliver(self, *, invite, raw_token: str) -> None:
        self._tokens_by_email[invite.email.lower()] = raw_token

    def token_for_email(self, email: str) -> str:
        return self._tokens_by_email[email.lower()]

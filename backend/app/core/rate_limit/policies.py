from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RateLimitPolicy:
    name: str
    limit: int
    window_seconds: int
    fail_open: bool


INVITE_ACCEPT_POLICY = RateLimitPolicy(
    name="invite_accept",
    limit=5,
    window_seconds=300,
    fail_open=False,
)

INVITE_CREATE_POLICY = RateLimitPolicy(
    name="invite_create",
    limit=20,
    window_seconds=3600,
    fail_open=False,
)

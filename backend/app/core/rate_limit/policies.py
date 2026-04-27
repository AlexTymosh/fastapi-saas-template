from __future__ import annotations

from dataclasses import dataclass

from limits import RateLimitItemPerHour, RateLimitItemPerMinute
from limits.limits import RateLimitItem


@dataclass(frozen=True)
class RateLimitPolicy:
    name: str
    item: RateLimitItem
    fail_open: bool


INVITE_ACCEPT_POLICY = RateLimitPolicy(
    name="invite_accept",
    item=RateLimitItemPerMinute(5, multiples=5),
    fail_open=False,
)

INVITE_CREATE_POLICY = RateLimitPolicy(
    name="invite_create",
    item=RateLimitItemPerHour(20),
    fail_open=False,
)

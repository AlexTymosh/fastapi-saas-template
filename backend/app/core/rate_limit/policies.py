from __future__ import annotations

from dataclasses import dataclass

from limits import RateLimitItemPerHour, RateLimitItemPerMinute
from limits.limits import RateLimitItem


@dataclass(frozen=True)
class RateLimitPolicy:
    name: str
    limit: RateLimitItem
    fail_open: bool
    sensitive: bool = False


INVITE_ACCEPT_POLICY = RateLimitPolicy(
    name="invite_accept",
    limit=RateLimitItemPerMinute(5, multiples=5),
    fail_open=False,
    sensitive=True,
)

INVITE_CREATE_POLICY = RateLimitPolicy(
    name="invite_create",
    limit=RateLimitItemPerHour(20),
    fail_open=False,
    sensitive=True,
)

from __future__ import annotations

from dataclasses import dataclass

from limits import RateLimitItemPerHour, RateLimitItemPerMinute, RateLimitItemPerSecond
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


def build_default_rate_limit_policy(
    *,
    default_limit: int,
    default_window_seconds: int,
    default_fail_open: bool,
) -> RateLimitPolicy:
    return RateLimitPolicy(
        name="default",
        item=RateLimitItemPerSecond(default_limit, multiples=default_window_seconds),
        fail_open=default_fail_open,
    )

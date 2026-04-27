from __future__ import annotations

from dataclasses import dataclass

from limits import RateLimitItemPerHour, RateLimitItemPerMinute, RateLimitItemPerSecond
from limits.limits import RateLimitItem

from app.core.config.settings import RateLimitingSettings


@dataclass(frozen=True)
class RateLimitPolicy:
    name: str
    item: RateLimitItem
    fail_open: bool


def build_default_rate_limit_policy(
    settings: RateLimitingSettings,
) -> RateLimitPolicy:
    return RateLimitPolicy(
        name="default",
        item=RateLimitItemPerSecond(
            settings.default_limit,
            multiples=settings.default_window_seconds,
        ),
        fail_open=settings.default_fail_open,
    )


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

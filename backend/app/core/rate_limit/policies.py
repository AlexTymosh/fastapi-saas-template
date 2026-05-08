from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from limits import RateLimitItemPerHour, RateLimitItemPerMinute, RateLimitItemPerSecond
from limits.limits import RateLimitItem

RateLimitSensitivity = Literal["normal", "sensitive", "critical"]


@dataclass(frozen=True)
class RateLimitPolicySpec:
    name: str
    default_limit: int
    default_window_seconds: int
    default_fail_open: bool
    sensitivity: RateLimitSensitivity


@dataclass(frozen=True)
class RateLimitPolicy:
    name: str
    item: RateLimitItem
    fail_open: bool
    sensitivity: RateLimitSensitivity = "normal"
    limit: int | None = None
    window_seconds: int | None = None
    override_applied: bool = False

    def __post_init__(self) -> None:
        if self.limit is None:
            object.__setattr__(self, "limit", self.item.amount)
        if self.window_seconds is None:
            object.__setattr__(self, "window_seconds", self.item.get_expiry())


def build_rate_limit_item(*, limit: int, window_seconds: int) -> RateLimitItem:
    if limit < 1:
        raise ValueError("Rate limit amount must be greater than zero")
    if window_seconds < 1:
        raise ValueError("Rate limit window must be greater than zero")
    if window_seconds == 60:
        return RateLimitItemPerMinute(limit)
    if window_seconds == 300:
        return RateLimitItemPerMinute(limit, multiples=5)
    if window_seconds == 3600:
        return RateLimitItemPerHour(limit)
    return RateLimitItemPerSecond(limit, multiples=window_seconds)


AUTHENTICATED_DEFAULT_POLICY = RateLimitPolicySpec(
    name="authenticated_default",
    default_limit=120,
    default_window_seconds=60,
    default_fail_open=True,
    sensitivity="normal",
)


TENANT_READ_POLICY = RateLimitPolicySpec(
    name="tenant_read",
    default_limit=120,
    default_window_seconds=60,
    default_fail_open=True,
    sensitivity="normal",
)


TENANT_WRITE_POLICY = RateLimitPolicySpec(
    name="tenant_write",
    default_limit=30,
    default_window_seconds=60,
    default_fail_open=False,
    sensitivity="sensitive",
)


ORGANISATION_CREATE_POLICY = RateLimitPolicySpec(
    name="organisation_create",
    default_limit=5,
    default_window_seconds=3600,
    default_fail_open=False,
    sensitivity="critical",
)


PLATFORM_READ_POLICY = RateLimitPolicySpec(
    name="platform_read",
    default_limit=60,
    default_window_seconds=60,
    default_fail_open=False,
    sensitivity="sensitive",
)


AUDIT_READ_POLICY = RateLimitPolicySpec(
    name="audit_read",
    default_limit=30,
    default_window_seconds=60,
    default_fail_open=False,
    sensitivity="critical",
)


INVITE_MUTATION_POLICY = RateLimitPolicySpec(
    name="invite_mutation",
    default_limit=30,
    default_window_seconds=3600,
    default_fail_open=False,
    sensitivity="sensitive",
)


INVITE_ACCEPT_POLICY = RateLimitPolicySpec(
    name="invite_accept",
    default_limit=5,
    default_window_seconds=300,
    default_fail_open=False,
    sensitivity="critical",
)

INVITE_CREATE_POLICY = RateLimitPolicySpec(
    name="invite_create",
    default_limit=20,
    default_window_seconds=3600,
    default_fail_open=False,
    sensitivity="sensitive",
)


PLATFORM_WRITE_POLICY = RateLimitPolicySpec(
    name="platform_write",
    default_limit=30,
    default_window_seconds=60,
    default_fail_open=False,
    sensitivity="critical",
)

PLATFORM_STAFF_WRITE_POLICY = RateLimitPolicySpec(
    name="platform_staff_write",
    default_limit=10,
    default_window_seconds=60,
    default_fail_open=False,
    sensitivity="critical",
)

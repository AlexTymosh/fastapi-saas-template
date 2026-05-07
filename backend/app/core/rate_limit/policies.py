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

INVITE_MUTATION_POLICY = RateLimitPolicy(
    name="invite_mutation",
    item=RateLimitItemPerHour(30),
    fail_open=False,
)

AUTHENTICATED_DEFAULT_POLICY = RateLimitPolicy(
    name="authenticated_default",
    item=RateLimitItemPerMinute(120),
    fail_open=True,
)

TENANT_READ_POLICY = RateLimitPolicy(
    name="tenant_read",
    item=RateLimitItemPerMinute(120),
    fail_open=True,
)

TENANT_WRITE_POLICY = RateLimitPolicy(
    name="tenant_write",
    item=RateLimitItemPerMinute(30),
    fail_open=False,
)

ORGANISATION_CREATE_POLICY = RateLimitPolicy(
    name="organisation_create",
    item=RateLimitItemPerHour(5),
    fail_open=False,
)

PLATFORM_READ_POLICY = RateLimitPolicy(
    name="platform_read",
    item=RateLimitItemPerMinute(60),
    fail_open=False,
)

AUDIT_READ_POLICY = RateLimitPolicy(
    name="audit_read",
    item=RateLimitItemPerMinute(30),
    fail_open=False,
)


PLATFORM_WRITE_POLICY = RateLimitPolicy(
    name="platform_write",
    item=RateLimitItemPerMinute(30),
    fail_open=False,
)

PLATFORM_STAFF_WRITE_POLICY = RateLimitPolicy(
    name="platform_staff_write",
    item=RateLimitItemPerMinute(10),
    fail_open=False,
)

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

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
    override_applied: bool = False


PRE_AUTH_POLICY = RateLimitPolicySpec(
    name="pre_auth",
    default_limit=120,
    default_window_seconds=60,
    default_fail_open=True,
    sensitivity="sensitive",
)


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


TENANT_WRITE_ORGANISATION_POLICY = RateLimitPolicySpec(
    name="tenant_write_organisation",
    default_limit=60,
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


INVITE_ACCEPT_TOKEN_POLICY = RateLimitPolicySpec(
    name="invite_accept_token",
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


INVITE_CREATE_ORGANISATION_POLICY = RateLimitPolicySpec(
    name="invite_create_organisation",
    default_limit=50,
    default_window_seconds=3600,
    default_fail_open=False,
    sensitivity="sensitive",
)


INVITE_CREATE_ORGANISATION_DAILY_POLICY = RateLimitPolicySpec(
    name="invite_create_organisation_daily",
    default_limit=200,
    default_window_seconds=86400,
    default_fail_open=False,
    sensitivity="critical",
)


INVITE_CREATE_TARGET_EMAIL_POLICY = RateLimitPolicySpec(
    name="invite_create_target_email",
    default_limit=3,
    default_window_seconds=86400,
    default_fail_open=False,
    sensitivity="critical",
)


INVITE_CREATE_TARGET_DOMAIN_POLICY = RateLimitPolicySpec(
    name="invite_create_target_domain",
    default_limit=50,
    default_window_seconds=86400,
    default_fail_open=False,
    sensitivity="sensitive",
)


INVITE_RESEND_INVITE_POLICY = RateLimitPolicySpec(
    name="invite_resend_invite",
    default_limit=5,
    default_window_seconds=3600,
    default_fail_open=False,
    sensitivity="sensitive",
)


INVITE_RESEND_ORGANISATION_DAILY_POLICY = RateLimitPolicySpec(
    name="invite_resend_organisation_daily",
    default_limit=200,
    default_window_seconds=86400,
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

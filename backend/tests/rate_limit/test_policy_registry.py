from __future__ import annotations

import pytest
from limits import RateLimitItemPerMinute

from app.core.config.settings import (
    RateLimitingSettings,
    RateLimitPolicyOverride,
    Settings,
)
from app.core.rate_limit.policies import (
    AUDIT_READ_POLICY,
    AUTHENTICATED_DEFAULT_POLICY,
    INVITE_ACCEPT_POLICY,
    INVITE_CREATE_POLICY,
    INVITE_MUTATION_POLICY,
    ORGANISATION_CREATE_POLICY,
    PLATFORM_READ_POLICY,
    PLATFORM_STAFF_WRITE_POLICY,
    PLATFORM_WRITE_POLICY,
    TENANT_READ_POLICY,
    TENANT_WRITE_POLICY,
    RateLimitPolicy,
    RateLimitPolicySpec,
)
from app.core.rate_limit.registry import (
    build_effective_policy_registry,
    build_policy_registry,
    build_policy_spec_registry,
    get_rate_limit_policy,
    iter_rate_limit_policies,
)

pytestmark = [pytest.mark.security, pytest.mark.rate_limit]

EXPECTED_POLICIES = {
    "authenticated_default": AUTHENTICATED_DEFAULT_POLICY,
    "tenant_read": TENANT_READ_POLICY,
    "tenant_write": TENANT_WRITE_POLICY,
    "organisation_create": ORGANISATION_CREATE_POLICY,
    "invite_accept": INVITE_ACCEPT_POLICY,
    "invite_create": INVITE_CREATE_POLICY,
    "invite_mutation": INVITE_MUTATION_POLICY,
    "platform_read": PLATFORM_READ_POLICY,
    "audit_read": AUDIT_READ_POLICY,
    "platform_write": PLATFORM_WRITE_POLICY,
    "platform_staff_write": PLATFORM_STAFF_WRITE_POLICY,
}


def _settings(
    *,
    mode: str = "normal",
    policies: dict[str, RateLimitPolicyOverride] | None = None,
) -> Settings:
    return Settings(
        rate_limiting=RateLimitingSettings(
            mode=mode,  # type: ignore[arg-type]
            policies=policies or {},
        ),
    )


def _effective(
    policy_name: str,
    *,
    mode: str = "normal",
    policies: dict[str, RateLimitPolicyOverride] | None = None,
) -> RateLimitPolicy:
    return build_effective_policy_registry(_settings(mode=mode, policies=policies))[
        policy_name
    ]


def test_registry_contains_all_rate_limit_policy_specs() -> None:
    names = {policy.name for policy in iter_rate_limit_policies()}

    assert names == set(EXPECTED_POLICIES)


@pytest.mark.parametrize("policy_name", sorted(EXPECTED_POLICIES))
def test_registry_returns_policy_spec_by_name(policy_name: str) -> None:
    assert get_rate_limit_policy(policy_name) is EXPECTED_POLICIES[policy_name]


def test_iter_rate_limit_policies_returns_all_policy_specs() -> None:
    policies = iter_rate_limit_policies()

    assert isinstance(policies, tuple)
    assert {policy.name for policy in policies} == set(EXPECTED_POLICIES)


def test_registered_policy_names_are_unique() -> None:
    names = [policy.name for policy in iter_rate_limit_policies()]

    assert len(names) == len(set(names))


def test_default_effective_policies_preserve_existing_semantics() -> None:
    registry = build_effective_policy_registry(_settings())

    assert registry["authenticated_default"].limit == 120
    assert registry["authenticated_default"].window_seconds == 60
    assert registry["authenticated_default"].fail_open is True

    assert registry["tenant_read"].limit == 120
    assert registry["tenant_read"].window_seconds == 60
    assert registry["tenant_read"].fail_open is True

    assert registry["tenant_write"].limit == 30
    assert registry["tenant_write"].window_seconds == 60
    assert registry["tenant_write"].fail_open is False

    assert registry["organisation_create"].limit == 5
    assert registry["organisation_create"].window_seconds == 3600
    assert registry["organisation_create"].fail_open is False

    assert registry["platform_read"].limit == 60
    assert registry["platform_read"].window_seconds == 60
    assert registry["platform_read"].fail_open is False

    assert registry["audit_read"].limit == 30
    assert registry["audit_read"].window_seconds == 60
    assert registry["audit_read"].fail_open is False

    assert registry["platform_write"].limit == 30
    assert registry["platform_write"].window_seconds == 60
    assert registry["platform_write"].fail_open is False

    assert registry["platform_staff_write"].limit == 10
    assert registry["platform_staff_write"].window_seconds == 60
    assert registry["platform_staff_write"].fail_open is False

    assert registry["invite_accept"].limit == 5
    assert registry["invite_accept"].item.multiples == 5
    assert registry["invite_accept"].window_seconds == 300
    assert registry["invite_accept"].fail_open is False

    assert registry["invite_create"].limit == 20
    assert registry["invite_create"].window_seconds == 3600
    assert registry["invite_create"].fail_open is False

    assert registry["invite_mutation"].limit == 30
    assert registry["invite_mutation"].window_seconds == 3600
    assert registry["invite_mutation"].fail_open is False


def test_override_changes_limit_window_and_fail_open() -> None:
    policy = _effective(
        "tenant_write",
        policies={
            "tenant_write": RateLimitPolicyOverride(
                limit=7,
                window_seconds=120,
                fail_open=True,
            ),
        },
    )

    assert policy.limit == 7
    assert policy.window_seconds == 120
    assert policy.item.amount == 7
    assert policy.item.get_expiry() == 120
    assert policy.fail_open is True
    assert policy.override_applied is True


def test_strict_mode_makes_limits_stricter_without_changing_window() -> None:
    policy = _effective("tenant_write", mode="strict")

    assert policy.limit == 15
    assert policy.window_seconds == 60
    assert policy.fail_open is False


def test_strict_mode_keeps_explicit_override_precedence() -> None:
    policy = _effective(
        "tenant_write",
        mode="strict",
        policies={"tenant_write": RateLimitPolicyOverride(limit=25)},
    )

    assert policy.limit == 25


def test_relaxed_mode_makes_limits_more_permissive() -> None:
    policy = _effective("tenant_write", mode="relaxed")

    assert policy.limit == 60
    assert policy.window_seconds == 60
    assert policy.fail_open is False


def test_panic_mode_makes_sensitive_and_critical_policies_stricter() -> None:
    sensitive = _effective("tenant_write", mode="panic")
    critical = _effective("platform_staff_write", mode="panic")
    normal = _effective("tenant_read", mode="panic")

    assert sensitive.limit == 15
    assert sensitive.fail_open is False
    assert critical.limit == 2
    assert critical.fail_open is False
    assert normal.limit == 120
    assert normal.fail_open is True


def test_panic_mode_does_not_allow_sensitive_or_critical_fail_open_override() -> None:
    registry = build_effective_policy_registry(
        _settings(
            mode="panic",
            policies={
                "tenant_write": RateLimitPolicyOverride(fail_open=True),
                "platform_write": RateLimitPolicyOverride(fail_open=True),
            },
        )
    )

    assert registry["tenant_write"].fail_open is False
    assert registry["platform_write"].fail_open is False


def test_runtime_duplicate_policy_names_are_rejected() -> None:
    policies = (
        RateLimitPolicy(
            name="duplicate",
            item=RateLimitItemPerMinute(1),
            fail_open=False,
        ),
        RateLimitPolicy(
            name="duplicate",
            item=RateLimitItemPerMinute(2),
            fail_open=True,
        ),
    )

    with pytest.raises(ValueError, match="Duplicate rate limit policy name"):
        build_policy_registry(policies)


def test_spec_duplicate_policy_names_are_rejected() -> None:
    policies = (
        RateLimitPolicySpec(
            name="duplicate",
            default_limit=1,
            default_window_seconds=60,
            default_fail_open=False,
            sensitivity="normal",
        ),
        RateLimitPolicySpec(
            name="duplicate",
            default_limit=2,
            default_window_seconds=60,
            default_fail_open=True,
            sensitivity="normal",
        ),
    )

    with pytest.raises(ValueError, match="Duplicate rate limit policy name"):
        build_policy_spec_registry(policies)


def test_unknown_policy_name_raises_clear_error() -> None:
    with pytest.raises(ValueError, match="Unknown rate limit policy: missing"):
        get_rate_limit_policy("missing")

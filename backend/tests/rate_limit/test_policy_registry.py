from __future__ import annotations

import pytest

from app.core.config.settings import RateLimitPolicyOverride, Settings
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
    RateLimitPolicySpec,
)
from app.core.rate_limit.registry import (
    build_effective_policy_registry,
    build_policy_registry,
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
        rate_limiting={"mode": mode, "policies": policies or {}},
        outbox={"invite_delivery_enabled": False},
    )


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


def test_default_effective_policies_preserve_current_behaviour() -> None:
    registry = build_effective_policy_registry(_settings())

    assert registry["authenticated_default"].item.amount == 120
    assert registry["authenticated_default"].item.get_expiry() == 60
    assert registry["authenticated_default"].fail_open is True

    assert registry["tenant_read"].item.amount == 120
    assert registry["tenant_read"].item.get_expiry() == 60
    assert registry["tenant_read"].fail_open is True

    assert registry["tenant_write"].item.amount == 30
    assert registry["tenant_write"].item.get_expiry() == 60
    assert registry["tenant_write"].fail_open is False

    assert registry["organisation_create"].item.amount == 5
    assert registry["organisation_create"].item.get_expiry() == 3600
    assert registry["organisation_create"].fail_open is False

    assert registry["platform_read"].item.amount == 60
    assert registry["platform_read"].item.get_expiry() == 60
    assert registry["platform_read"].fail_open is False

    assert registry["audit_read"].item.amount == 30
    assert registry["audit_read"].item.get_expiry() == 60
    assert registry["audit_read"].fail_open is False

    assert registry["platform_write"].item.amount == 30
    assert registry["platform_write"].item.get_expiry() == 60
    assert registry["platform_write"].fail_open is False

    assert registry["platform_staff_write"].item.amount == 10
    assert registry["platform_staff_write"].item.get_expiry() == 60
    assert registry["platform_staff_write"].fail_open is False

    assert registry["invite_accept"].item.amount == 5
    assert registry["invite_accept"].item.multiples == 5
    assert registry["invite_accept"].item.get_expiry() == 300
    assert registry["invite_accept"].fail_open is False

    assert registry["invite_create"].item.amount == 20
    assert registry["invite_create"].item.get_expiry() == 3600
    assert registry["invite_create"].fail_open is False

    assert registry["invite_mutation"].item.amount == 30
    assert registry["invite_mutation"].item.get_expiry() == 3600
    assert registry["invite_mutation"].fail_open is False


def test_duplicate_policy_names_are_rejected() -> None:
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
        build_policy_registry(policies)


def test_unknown_policy_name_raises_clear_error() -> None:
    with pytest.raises(ValueError, match="Unknown rate limit policy: missing"):
        get_rate_limit_policy("missing")


def test_override_changes_limit_window_and_fail_open() -> None:
    registry = build_effective_policy_registry(
        _settings(
            policies={
                "tenant_write": RateLimitPolicyOverride(
                    limit=7,
                    window_seconds=300,
                    fail_open=True,
                )
            }
        )
    )

    policy = registry["tenant_write"]
    assert policy.item.amount == 7
    assert policy.item.multiples == 5
    assert policy.item.get_expiry() == 300
    assert policy.fail_open is True
    assert policy.override_applied is True


@pytest.mark.parametrize(
    ("mode", "policy_name", "expected_limit"),
    [
        ("strict", "tenant_read", 60),
        ("relaxed", "tenant_read", 240),
        ("panic", "tenant_write", 15),
        ("panic", "platform_write", 7),
    ],
)
def test_modes_transform_effective_limits(
    mode: str, policy_name: str, expected_limit: int
) -> None:
    registry = build_effective_policy_registry(_settings(mode=mode))

    assert registry[policy_name].item.amount == expected_limit


def test_panic_forces_sensitive_and_critical_fail_closed() -> None:
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
    assert registry["tenant_read"].fail_open is True


def test_explicit_override_takes_precedence_after_strict_mode() -> None:
    registry = build_effective_policy_registry(
        _settings(
            mode="strict",
            policies={"tenant_write": RateLimitPolicyOverride(limit=25)},
        )
    )

    assert registry["tenant_write"].item.amount == 25


def test_nested_policy_override_env_shape(monkeypatch) -> None:
    monkeypatch.setenv("RATE_LIMITING__POLICIES__TENANT_WRITE__LIMIT", "9")

    settings = Settings(outbox={"invite_delivery_enabled": False})

    # pydantic-settings lower-cases nested env keys with default case-insensitive
    # parsing, so production policy names remain snake_case.
    assert settings.rate_limiting.policies["tenant_write"].limit == 9

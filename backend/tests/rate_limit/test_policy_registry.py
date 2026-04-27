from __future__ import annotations

import pytest
from limits import RateLimitItemPerMinute

from app.core.config.settings import RateLimitingSettings
from app.core.rate_limit.policies import RateLimitPolicy
from app.core.rate_limit.registry import (
    build_policy_registry,
    create_explicit_default_policy,
    get_rate_limit_policy,
    iter_rate_limit_policies,
)


def test_registry_contains_invite_policies() -> None:
    names = {policy.name for policy in iter_rate_limit_policies()}

    assert "invite_accept" in names
    assert "invite_create" in names


def test_registry_returns_policy_by_name() -> None:
    invite_accept = get_rate_limit_policy("invite_accept")
    invite_create = get_rate_limit_policy("invite_create")

    assert invite_accept.name == "invite_accept"
    assert invite_create.name == "invite_create"


def test_iter_rate_limit_policies_returns_all_policies() -> None:
    policies = iter_rate_limit_policies()

    assert isinstance(policies, tuple)
    assert {policy.name for policy in policies} == {"invite_accept", "invite_create"}


def test_duplicate_policy_names_are_rejected() -> None:
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


def test_unknown_policy_name_raises_clear_error() -> None:
    with pytest.raises(ValueError, match="Unknown rate limit policy: missing"):
        get_rate_limit_policy("missing")


def test_explicit_default_policy_factory_uses_configured_values() -> None:
    settings = RateLimitingSettings(
        default_limit=77,
        default_window_seconds=123,
        default_fail_open=False,
    )

    default_policy = create_explicit_default_policy(settings)

    assert default_policy.name == "default"
    assert default_policy.item.amount == 77
    assert default_policy.item.get_expiry() == 123
    assert default_policy.fail_open is False


def test_explicit_default_policy_is_not_auto_registered() -> None:
    names = {policy.name for policy in iter_rate_limit_policies()}
    assert "default" not in names

    with pytest.raises(ValueError, match="Unknown rate limit policy: default"):
        get_rate_limit_policy("default")


def test_invite_policy_semantics_are_unchanged() -> None:
    invite_accept = get_rate_limit_policy("invite_accept")
    invite_create = get_rate_limit_policy("invite_create")

    assert invite_accept.item.amount == 5
    assert invite_accept.item.multiples == 5
    assert invite_accept.item.get_expiry() == 300
    assert invite_accept.fail_open is False

    assert invite_create.item.amount == 20
    assert invite_create.item.get_expiry() == 3600
    assert invite_create.fail_open is False

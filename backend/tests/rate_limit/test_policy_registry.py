from __future__ import annotations

import pytest
from limits import RateLimitItemPerMinute

from app.core.rate_limit.policies import (
    INVITE_ACCEPT_POLICY,
    INVITE_CREATE_POLICY,
    RateLimitPolicy,
)
from app.core.rate_limit.registry import (
    _build_registry,
    get_rate_limit_policy,
    iter_rate_limit_policies,
)


def test_policy_registry_contains_invite_policies() -> None:
    policies = iter_rate_limit_policies()

    names = {policy.name for policy in policies}
    assert "invite_accept" in names
    assert "invite_create" in names


def test_get_rate_limit_policy_returns_expected_policy() -> None:
    assert get_rate_limit_policy("invite_accept") is INVITE_ACCEPT_POLICY
    assert get_rate_limit_policy("invite_create") is INVITE_CREATE_POLICY


def test_iter_rate_limit_policies_returns_all_declared_policies() -> None:
    policies = iter_rate_limit_policies()

    assert INVITE_ACCEPT_POLICY in policies
    assert INVITE_CREATE_POLICY in policies


def test_duplicate_policy_names_are_rejected() -> None:
    duplicate = RateLimitPolicy(
        name="invite_accept",
        item=RateLimitItemPerMinute(1),
        fail_open=False,
    )

    with pytest.raises(ValueError, match="Duplicate rate limit policy name"):
        _build_registry((INVITE_ACCEPT_POLICY, duplicate))


def test_unknown_policy_name_raises_clear_error() -> None:
    with pytest.raises(KeyError, match="Unknown rate limit policy: unknown"):
        get_rate_limit_policy("unknown")


def test_policy_semantics_remain_unchanged() -> None:
    assert INVITE_ACCEPT_POLICY.item.amount == 5
    assert INVITE_ACCEPT_POLICY.item.multiples == 5
    assert INVITE_ACCEPT_POLICY.item.get_expiry() == 300
    assert INVITE_ACCEPT_POLICY.fail_open is False

    assert INVITE_CREATE_POLICY.item.amount == 20
    assert INVITE_CREATE_POLICY.item.get_expiry() == 3600
    assert INVITE_CREATE_POLICY.fail_open is False

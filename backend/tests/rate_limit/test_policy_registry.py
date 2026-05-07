from __future__ import annotations

import pytest
from limits import RateLimitItemPerMinute

from app.core.rate_limit.policies import (
    AUDIT_READ_POLICY,
    AUTHENTICATED_DEFAULT_POLICY,
    INVITE_MUTATION_POLICY,
    ORGANISATION_CREATE_POLICY,
    PLATFORM_READ_POLICY,
    PLATFORM_STAFF_WRITE_POLICY,
    PLATFORM_WRITE_POLICY,
    TENANT_READ_POLICY,
    TENANT_WRITE_POLICY,
    RateLimitPolicy,
)
from app.core.rate_limit.registry import (
    build_policy_registry,
    get_rate_limit_policy,
    iter_rate_limit_policies,
)

pytestmark = [pytest.mark.security, pytest.mark.rate_limit]

EXPECTED_POLICY_NAMES = {
    "authenticated_default",
    "tenant_read",
    "tenant_write",
    "organisation_create",
    "invite_accept",
    "invite_create",
    "invite_mutation",
    "platform_read",
    "audit_read",
    "platform_write",
    "platform_staff_write",
}


def test_registry_contains_all_endpoint_policies() -> None:
    names = {policy.name for policy in iter_rate_limit_policies()}

    assert names == EXPECTED_POLICY_NAMES


@pytest.mark.parametrize("policy_name", sorted(EXPECTED_POLICY_NAMES))
def test_registry_returns_every_policy_by_name(policy_name: str) -> None:
    policy = get_rate_limit_policy(policy_name)

    assert policy.name == policy_name


def test_iter_rate_limit_policies_returns_all_policies() -> None:
    policies = iter_rate_limit_policies()

    assert isinstance(policies, tuple)
    assert {policy.name for policy in policies} == EXPECTED_POLICY_NAMES


def test_registered_policy_names_are_unique() -> None:
    names = [policy.name for policy in iter_rate_limit_policies()]

    assert len(names) == len(set(names))


def test_new_authenticated_and_tenant_policy_semantics() -> None:
    assert (
        get_rate_limit_policy("authenticated_default") is AUTHENTICATED_DEFAULT_POLICY
    )
    assert AUTHENTICATED_DEFAULT_POLICY.item.amount == 120
    assert AUTHENTICATED_DEFAULT_POLICY.item.get_expiry() == 60
    assert AUTHENTICATED_DEFAULT_POLICY.fail_open is True

    assert get_rate_limit_policy("tenant_read") is TENANT_READ_POLICY
    assert TENANT_READ_POLICY.item.amount == 120
    assert TENANT_READ_POLICY.item.get_expiry() == 60
    assert TENANT_READ_POLICY.fail_open is True

    assert get_rate_limit_policy("tenant_write") is TENANT_WRITE_POLICY
    assert TENANT_WRITE_POLICY.item.amount == 30
    assert TENANT_WRITE_POLICY.item.get_expiry() == 60
    assert TENANT_WRITE_POLICY.fail_open is False

    assert get_rate_limit_policy("organisation_create") is ORGANISATION_CREATE_POLICY
    assert ORGANISATION_CREATE_POLICY.item.amount == 5
    assert ORGANISATION_CREATE_POLICY.item.get_expiry() == 3600
    assert ORGANISATION_CREATE_POLICY.fail_open is False


def test_new_platform_and_audit_policy_semantics() -> None:
    assert get_rate_limit_policy("platform_read") is PLATFORM_READ_POLICY
    assert PLATFORM_READ_POLICY.item.amount == 60
    assert PLATFORM_READ_POLICY.item.get_expiry() == 60
    assert PLATFORM_READ_POLICY.fail_open is False

    assert get_rate_limit_policy("audit_read") is AUDIT_READ_POLICY
    assert AUDIT_READ_POLICY.item.amount == 30
    assert AUDIT_READ_POLICY.item.get_expiry() == 60
    assert AUDIT_READ_POLICY.fail_open is False


def test_platform_write_policy_semantics() -> None:
    platform_write = get_rate_limit_policy("platform_write")
    platform_staff_write = get_rate_limit_policy("platform_staff_write")

    assert platform_write is PLATFORM_WRITE_POLICY
    assert platform_write.item.amount == 30
    assert platform_write.item.get_expiry() == 60
    assert platform_write.fail_open is False

    assert platform_staff_write is PLATFORM_STAFF_WRITE_POLICY
    assert platform_staff_write.item.amount == 10
    assert platform_staff_write.item.get_expiry() == 60
    assert platform_staff_write.fail_open is False


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


def test_invite_policy_semantics_are_unchanged_except_admin_mutation_policy() -> None:
    invite_accept = get_rate_limit_policy("invite_accept")
    invite_create = get_rate_limit_policy("invite_create")
    invite_mutation = get_rate_limit_policy("invite_mutation")

    assert invite_accept.item.amount == 5
    assert invite_accept.item.multiples == 5
    assert invite_accept.item.get_expiry() == 300
    assert invite_accept.fail_open is False

    assert invite_create.item.amount == 20
    assert invite_create.item.get_expiry() == 3600
    assert invite_create.fail_open is False

    assert invite_mutation is INVITE_MUTATION_POLICY
    assert invite_mutation.item.amount == 30
    assert invite_mutation.item.get_expiry() == 3600
    assert invite_mutation.fail_open is False

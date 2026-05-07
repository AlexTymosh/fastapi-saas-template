from __future__ import annotations

from collections.abc import Iterable

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
)


def build_policy_registry(
    policies: Iterable[RateLimitPolicy],
) -> dict[str, RateLimitPolicy]:
    registry: dict[str, RateLimitPolicy] = {}
    for policy in policies:
        if policy.name in registry:
            raise ValueError(f"Duplicate rate limit policy name: {policy.name}")
        registry[policy.name] = policy
    return registry


_REGISTERED_POLICIES: tuple[RateLimitPolicy, ...] = (
    AUTHENTICATED_DEFAULT_POLICY,
    TENANT_READ_POLICY,
    TENANT_WRITE_POLICY,
    ORGANISATION_CREATE_POLICY,
    INVITE_ACCEPT_POLICY,
    INVITE_CREATE_POLICY,
    INVITE_MUTATION_POLICY,
    PLATFORM_READ_POLICY,
    AUDIT_READ_POLICY,
    PLATFORM_WRITE_POLICY,
    PLATFORM_STAFF_WRITE_POLICY,
)
_POLICY_REGISTRY = build_policy_registry(_REGISTERED_POLICIES)


def get_rate_limit_policy(name: str) -> RateLimitPolicy:
    try:
        return _POLICY_REGISTRY[name]
    except KeyError as exc:
        raise ValueError(f"Unknown rate limit policy: {name}") from exc


def iter_rate_limit_policies() -> tuple[RateLimitPolicy, ...]:
    return _REGISTERED_POLICIES

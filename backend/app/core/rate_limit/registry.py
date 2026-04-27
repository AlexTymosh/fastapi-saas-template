from __future__ import annotations

from app.core.rate_limit.policies import (
    INVITE_ACCEPT_POLICY,
    INVITE_CREATE_POLICY,
    RateLimitPolicy,
)


def _build_registry(
    policies: tuple[RateLimitPolicy, ...],
) -> dict[str, RateLimitPolicy]:
    registry: dict[str, RateLimitPolicy] = {}
    for policy in policies:
        if policy.name in registry:
            raise ValueError(f"Duplicate rate limit policy name: {policy.name}")
        registry[policy.name] = policy
    return registry


_DECLARED_POLICIES: tuple[RateLimitPolicy, ...] = (
    INVITE_ACCEPT_POLICY,
    INVITE_CREATE_POLICY,
)
_POLICY_REGISTRY = _build_registry(_DECLARED_POLICIES)


def get_rate_limit_policy(name: str) -> RateLimitPolicy:
    try:
        return _POLICY_REGISTRY[name]
    except KeyError as exc:
        raise KeyError(f"Unknown rate limit policy: {name}") from exc


def iter_rate_limit_policies() -> tuple[RateLimitPolicy, ...]:
    return tuple(_POLICY_REGISTRY.values())

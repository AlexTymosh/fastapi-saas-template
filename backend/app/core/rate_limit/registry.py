from __future__ import annotations

from collections.abc import Iterable

from app.core.config.settings import RateLimitingSettings
from app.core.rate_limit.policies import (
    INVITE_ACCEPT_POLICY,
    INVITE_CREATE_POLICY,
    RateLimitPolicy,
    build_default_rate_limit_policy,
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
    INVITE_ACCEPT_POLICY,
    INVITE_CREATE_POLICY,
)
_POLICY_REGISTRY = build_policy_registry(_REGISTERED_POLICIES)


def get_rate_limit_policy(name: str) -> RateLimitPolicy:
    try:
        return _POLICY_REGISTRY[name]
    except KeyError as exc:
        raise ValueError(f"Unknown rate limit policy: {name}") from exc


def iter_rate_limit_policies() -> tuple[RateLimitPolicy, ...]:
    return _REGISTERED_POLICIES


def create_explicit_default_policy(
    settings: RateLimitingSettings,
) -> RateLimitPolicy:
    return build_default_rate_limit_policy(settings=settings)

from __future__ import annotations

from collections.abc import Iterable, Mapping
from math import floor
from typing import TYPE_CHECKING

from fastapi import FastAPI

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
    build_rate_limit_item,
)

if TYPE_CHECKING:
    from app.core.config.settings import RateLimitPolicyOverride, Settings


def build_policy_spec_registry(
    policies: Iterable[RateLimitPolicySpec],
) -> dict[str, RateLimitPolicySpec]:
    registry: dict[str, RateLimitPolicySpec] = {}
    for policy in policies:
        if policy.name in registry:
            raise ValueError(f"Duplicate rate limit policy name: {policy.name}")
        registry[policy.name] = policy
    return registry


_REGISTERED_POLICY_SPECS: tuple[RateLimitPolicySpec, ...] = (
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
_POLICY_SPEC_REGISTRY = build_policy_spec_registry(_REGISTERED_POLICY_SPECS)


def _apply_mode_to_limit(*, limit: int, mode: str, sensitivity: str) -> int:
    if mode == "strict":
        return max(1, floor(limit * 0.5))
    if mode == "relaxed":
        return limit * 2
    if mode == "panic" and sensitivity == "sensitive":
        return max(1, floor(limit * 0.5))
    if mode == "panic" and sensitivity == "critical":
        return max(1, floor(limit * 0.25))
    return limit


def _apply_mode_to_fail_open(*, fail_open: bool, mode: str, sensitivity: str) -> bool:
    if mode == "panic" and sensitivity in {"sensitive", "critical"}:
        return False
    return fail_open


def build_policy_registry(
    policies: Iterable[RateLimitPolicy],
) -> dict[str, RateLimitPolicy]:
    registry: dict[str, RateLimitPolicy] = {}
    for policy in policies:
        if policy.name in registry:
            raise ValueError(f"Duplicate rate limit policy name: {policy.name}")
        registry[policy.name] = policy
    return registry


def build_effective_policy_registry(settings: Settings) -> dict[str, RateLimitPolicy]:
    mode = settings.rate_limiting.mode
    overrides: Mapping[str, RateLimitPolicyOverride] = settings.rate_limiting.policies
    effective_policies: list[RateLimitPolicy] = []

    for spec in _REGISTERED_POLICY_SPECS:
        override = overrides.get(spec.name)
        limit = _apply_mode_to_limit(
            limit=spec.default_limit,
            mode=mode,
            sensitivity=spec.sensitivity,
        )
        window_seconds = spec.default_window_seconds
        fail_open = _apply_mode_to_fail_open(
            fail_open=spec.default_fail_open,
            mode=mode,
            sensitivity=spec.sensitivity,
        )

        if override is not None:
            if override.limit is not None:
                limit = override.limit
            if override.window_seconds is not None:
                window_seconds = override.window_seconds
            if override.fail_open is not None:
                fail_open = override.fail_open

        fail_open = _apply_mode_to_fail_open(
            fail_open=fail_open,
            mode=mode,
            sensitivity=spec.sensitivity,
        )

        effective_policies.append(
            RateLimitPolicy(
                name=spec.name,
                item=build_rate_limit_item(
                    limit=limit,
                    window_seconds=window_seconds,
                ),
                fail_open=fail_open,
                sensitivity=spec.sensitivity,
                limit=limit,
                window_seconds=window_seconds,
                override_applied=override is not None,
            )
        )

    return build_policy_registry(effective_policies)


def get_rate_limit_policy(name: str) -> RateLimitPolicySpec:
    try:
        return _POLICY_SPEC_REGISTRY[name]
    except KeyError as exc:
        raise ValueError(f"Unknown rate limit policy: {name}") from exc


def get_effective_rate_limit_policy(app: FastAPI, policy_name: str) -> RateLimitPolicy:
    registry = getattr(app.state, "rate_limit_policy_registry", None)
    if registry is None:
        raise RuntimeError("Effective rate limit policy registry is unavailable")
    try:
        return registry[policy_name]
    except KeyError as exc:
        raise ValueError(f"Unknown rate limit policy: {policy_name}") from exc


def iter_rate_limit_policies() -> tuple[RateLimitPolicySpec, ...]:
    return _REGISTERED_POLICY_SPECS


def iter_rate_limit_policy_names() -> frozenset[str]:
    return frozenset(_POLICY_SPEC_REGISTRY)

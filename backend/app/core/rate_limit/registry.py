from __future__ import annotations

from collections.abc import Iterable, Mapping
from math import floor
from typing import TYPE_CHECKING

from fastapi import FastAPI
from limits import RateLimitItemPerDay, RateLimitItemPerHour, RateLimitItemPerMinute
from limits.limits import RateLimitItem

from app.core.rate_limit.policies import (
    AUDIT_READ_POLICY,
    AUTHENTICATED_DEFAULT_POLICY,
    INVITE_ACCEPT_POLICY,
    INVITE_CREATE_ORGANISATION_DAILY_POLICY,
    INVITE_CREATE_ORGANISATION_POLICY,
    INVITE_CREATE_POLICY,
    INVITE_CREATE_TARGET_DOMAIN_POLICY,
    INVITE_CREATE_TARGET_EMAIL_POLICY,
    INVITE_MUTATION_POLICY,
    INVITE_RESEND_INVITE_POLICY,
    INVITE_RESEND_ORGANISATION_DAILY_POLICY,
    ORGANISATION_CREATE_POLICY,
    PLATFORM_READ_POLICY,
    PLATFORM_STAFF_WRITE_POLICY,
    PLATFORM_WRITE_POLICY,
    PRE_AUTH_POLICY,
    TENANT_READ_POLICY,
    TENANT_WRITE_POLICY,
    RateLimitPolicy,
    RateLimitPolicySpec,
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


# Backwards-compatible alias for older tests/imports that validate duplicate names.
build_policy_registry = build_policy_spec_registry


def _rate_limit_item_from_window(*, limit: int, window_seconds: int) -> RateLimitItem:
    if window_seconds == 60:
        return RateLimitItemPerMinute(limit)
    if window_seconds == 300:
        return RateLimitItemPerMinute(limit, multiples=5)
    if window_seconds == 3600:
        return RateLimitItemPerHour(limit)
    if window_seconds == 86400:
        return RateLimitItemPerDay(limit)
    raise ValueError(
        "Unsupported rate limit window_seconds: "
        f"{window_seconds}. Supported values are 60, 300, 3600, and 86400."
    )


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


def _apply_override(
    *,
    spec: RateLimitPolicySpec,
    mode: str,
    override: RateLimitPolicyOverride | None,
) -> RateLimitPolicy:
    limit = _apply_mode_to_limit(
        limit=spec.default_limit,
        mode=mode,
        sensitivity=spec.sensitivity,
    )
    window_seconds = spec.default_window_seconds
    fail_open = spec.default_fail_open

    if mode == "panic" and spec.sensitivity in {"sensitive", "critical"}:
        fail_open = False

    override_applied = override is not None
    if override is not None:
        if override.limit is not None:
            limit = override.limit
        if override.window_seconds is not None:
            window_seconds = override.window_seconds
        if override.fail_open is not None:
            fail_open = override.fail_open

    if mode == "panic" and spec.sensitivity in {"sensitive", "critical"}:
        fail_open = False

    return RateLimitPolicy(
        name=spec.name,
        item=_rate_limit_item_from_window(limit=limit, window_seconds=window_seconds),
        fail_open=fail_open,
        sensitivity=spec.sensitivity,
        override_applied=override_applied,
    )


_REGISTERED_POLICY_SPECS: tuple[RateLimitPolicySpec, ...] = (
    PRE_AUTH_POLICY,
    AUTHENTICATED_DEFAULT_POLICY,
    TENANT_READ_POLICY,
    TENANT_WRITE_POLICY,
    ORGANISATION_CREATE_POLICY,
    INVITE_ACCEPT_POLICY,
    INVITE_CREATE_POLICY,
    INVITE_CREATE_ORGANISATION_POLICY,
    INVITE_CREATE_ORGANISATION_DAILY_POLICY,
    INVITE_CREATE_TARGET_EMAIL_POLICY,
    INVITE_CREATE_TARGET_DOMAIN_POLICY,
    INVITE_MUTATION_POLICY,
    INVITE_RESEND_INVITE_POLICY,
    INVITE_RESEND_ORGANISATION_DAILY_POLICY,
    PLATFORM_READ_POLICY,
    AUDIT_READ_POLICY,
    PLATFORM_WRITE_POLICY,
    PLATFORM_STAFF_WRITE_POLICY,
)
_POLICY_SPEC_REGISTRY = build_policy_spec_registry(_REGISTERED_POLICY_SPECS)


def get_rate_limit_policy(name: str) -> RateLimitPolicySpec:
    try:
        return _POLICY_SPEC_REGISTRY[name]
    except KeyError as exc:
        raise ValueError(f"Unknown rate limit policy: {name}") from exc


def iter_rate_limit_policies() -> tuple[RateLimitPolicySpec, ...]:
    return _REGISTERED_POLICY_SPECS


def get_known_rate_limit_policy_names() -> frozenset[str]:
    return frozenset(_POLICY_SPEC_REGISTRY)


def build_effective_policy_registry(settings: Settings) -> dict[str, RateLimitPolicy]:
    overrides = settings.rate_limiting.policies
    unknown_names = sorted(set(overrides) - set(_POLICY_SPEC_REGISTRY))
    if unknown_names:
        raise ValueError(
            "Unknown rate limit policy override name(s): " + ", ".join(unknown_names)
        )

    return {
        spec.name: _apply_override(
            spec=spec,
            mode=settings.rate_limiting.mode,
            override=overrides.get(spec.name),
        )
        for spec in _REGISTERED_POLICY_SPECS
    }


def get_effective_rate_limit_policy(app: FastAPI, policy_name: str) -> RateLimitPolicy:
    registry: Mapping[str, RateLimitPolicy] | None = getattr(
        app.state,
        "rate_limit_policy_registry",
        None,
    )
    if registry is None:
        raise RuntimeError("Rate limit policy registry has not been initialised")
    try:
        return registry[policy_name]
    except KeyError as exc:
        raise ValueError(f"Unknown rate limit policy: {policy_name}") from exc

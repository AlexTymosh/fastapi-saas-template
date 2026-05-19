from __future__ import annotations

import asyncio
import math
import time
from collections.abc import Awaitable, Callable
from typing import Annotated, Any

from fastapi import Depends, Request
from redis.exceptions import ConnectionError as RedisConnectionError
from redis.exceptions import TimeoutError as RedisTimeoutError

from app.core.auth import AuthenticatedPrincipal, require_authenticated_principal
from app.core.config.settings import get_settings
from app.core.errors import RateLimiterUnavailableError, TooManyRequestsError
from app.core.logging import get_logger
from app.core.observability import (
    record_rate_limit_backend_error,
    record_rate_limit_check_duration,
    record_rate_limit_decision,
)
from app.core.rate_limit.identifiers import (
    RateLimitBucket,
    RateLimitIdentifier,
    build_bucket_identifier,
    build_identifier,
)
from app.core.rate_limit.policies import (
    PRE_AUTH_POLICY,
    RateLimitPolicy,
    RateLimitPolicySpec,
)
from app.core.rate_limit.registry import get_effective_rate_limit_policy

log = get_logger(__name__)


async def _await_with_timeout(awaitable: Awaitable[Any], timeout_seconds: float) -> Any:
    return await asyncio.wait_for(awaitable, timeout=timeout_seconds)


def _runtime_from_request(request: Request) -> Any | None:
    return getattr(request.app.state, "rate_limiter_runtime", None)


def _settings_from_request(request: Request) -> Any:
    return getattr(request.app.state, "settings", None) or get_settings()


def _build_retry_after(reset_time: float) -> str:
    retry_after = max(1, math.ceil(reset_time - time.time()))
    return str(retry_after)


def _record_rate_limit_outcome(
    *,
    policy_name: str,
    result: str,
    identifier_kind: str,
    started_at: float,
) -> None:
    duration_seconds = time.perf_counter() - started_at
    record_rate_limit_decision(
        policy_name=policy_name,
        result=result,
        identifier_kind=identifier_kind,
    )
    record_rate_limit_check_duration(
        policy_name=policy_name,
        result=result,
        identifier_kind=identifier_kind,
        duration_seconds=duration_seconds,
    )


async def _check_rate_limit_for_identifier(
    *,
    request: Request,
    policy: RateLimitPolicy,
    identifier: RateLimitIdentifier,
    started_at: float,
) -> None:
    settings = _settings_from_request(request)
    runtime = _runtime_from_request(request)

    if runtime is None or runtime.limiter is None:
        record_rate_limit_backend_error(
            policy_name=policy.name,
            identifier_kind="unknown",
            error_type="RuntimeUnavailable",
        )
        _record_rate_limit_outcome(
            policy_name=policy.name,
            result="runtime_unavailable",
            identifier_kind="unknown",
            started_at=started_at,
        )
        raise RateLimiterUnavailableError(
            detail="Rate limiter is unavailable.",
        )

    namespace = f"{settings.rate_limiting.redis_prefix}:{policy.name}:{identifier.kind}"
    item = policy.item

    try:
        allowed = await _await_with_timeout(
            runtime.limiter.hit(item, namespace, identifier.bucket_key),
            timeout_seconds=settings.rate_limiting.storage_timeout_seconds,
        )
    except (
        RedisConnectionError,
        RedisTimeoutError,
        TimeoutError,
        RuntimeError,
    ) as exc:
        record_rate_limit_backend_error(
            policy_name=policy.name,
            identifier_kind=identifier.kind,
            error_type=exc.__class__.__name__,
        )

        if policy.fail_open:
            _record_rate_limit_outcome(
                policy_name=policy.name,
                result="fail_open",
                identifier_kind=identifier.kind,
                started_at=started_at,
            )
            log.warning(
                "rate_limiter_fail_open",
                policy=policy.name,
                identifier_kind=identifier.kind,
                reason=exc.__class__.__name__,
                category="security",
            )
            return

        _record_rate_limit_outcome(
            policy_name=policy.name,
            result="backend_error",
            identifier_kind=identifier.kind,
            started_at=started_at,
        )
        raise RateLimiterUnavailableError(
            detail="Rate limiter is temporarily unavailable.",
        ) from exc

    if allowed:
        _record_rate_limit_outcome(
            policy_name=policy.name,
            result="allowed",
            identifier_kind=identifier.kind,
            started_at=started_at,
        )
        return

    _record_rate_limit_outcome(
        policy_name=policy.name,
        result="blocked",
        identifier_kind=identifier.kind,
        started_at=started_at,
    )

    try:
        window = await _await_with_timeout(
            runtime.limiter.get_window_stats(
                item,
                namespace,
                identifier.bucket_key,
            ),
            timeout_seconds=settings.rate_limiting.storage_timeout_seconds,
        )
        retry_after = _build_retry_after(window.reset_time)
    except (
        RedisConnectionError,
        RedisTimeoutError,
        TimeoutError,
        RuntimeError,
    ):
        retry_after = str(policy.item.get_expiry())

    raise TooManyRequestsError(
        detail="Too many requests.",
        headers={
            "Retry-After": retry_after,
            "Access-Control-Expose-Headers": "Retry-After",
        },
    )


def _effective_policy(
    *, request: Request, policy: RateLimitPolicy | RateLimitPolicySpec
) -> RateLimitPolicy:
    if isinstance(policy, RateLimitPolicySpec):
        return get_effective_rate_limit_policy(request.app, policy.name)
    return policy


def _identifier_secret_or_error(
    *,
    request: Request,
    policy_name: str,
    started_at: float,
) -> str:
    settings = _settings_from_request(request)
    identifier_secret = settings.rate_limiting.identifier_secret
    if identifier_secret is None:
        record_rate_limit_backend_error(
            policy_name=policy_name,
            identifier_kind="unknown",
            error_type="IdentifierSecretUnavailable",
        )
        _record_rate_limit_outcome(
            policy_name=policy_name,
            result="runtime_unavailable",
            identifier_kind="unknown",
            started_at=started_at,
        )
        raise RateLimiterUnavailableError(
            detail="Rate limiter is unavailable.",
        )
    if hasattr(identifier_secret, "get_secret_value"):
        return identifier_secret.get_secret_value()
    return str(identifier_secret)


async def check_rate_limit_for_bucket(
    *,
    request: Request,
    bucket: RateLimitBucket,
    policy: RateLimitPolicy | RateLimitPolicySpec,
) -> None:
    settings = _settings_from_request(request)

    if not settings.rate_limiting.enabled:
        return

    effective_policy = _effective_policy(request=request, policy=policy)
    started_at = time.perf_counter()
    identifier_secret = _identifier_secret_or_error(
        request=request,
        policy_name=effective_policy.name,
        started_at=started_at,
    )
    identifier = build_bucket_identifier(
        bucket=bucket,
        identifier_secret=identifier_secret,
    )
    await _check_rate_limit_for_identifier(
        request=request,
        policy=effective_policy,
        identifier=identifier,
        started_at=started_at,
    )


async def check_rate_limits_for_buckets(
    *,
    request: Request,
    checks: list[tuple[RateLimitPolicy | RateLimitPolicySpec, RateLimitBucket]],
) -> None:
    for policy, bucket in checks:
        await check_rate_limit_for_bucket(
            request=request,
            bucket=bucket,
            policy=policy,
        )


async def check_pre_auth_rate_limit(
    *,
    request: Request,
    policy: RateLimitPolicy | RateLimitPolicySpec = PRE_AUTH_POLICY,
) -> None:
    settings = _settings_from_request(request)

    if (
        not settings.rate_limiting.enabled
        or not settings.rate_limiting.pre_auth_enabled
    ):
        return

    effective_policy = _effective_policy(request=request, policy=policy)
    started_at = time.perf_counter()
    identifier_secret = _identifier_secret_or_error(
        request=request,
        policy_name=effective_policy.name,
        started_at=started_at,
    )

    identifier = build_identifier(
        principal=None,
        request=request,
        trust_proxy_headers=settings.rate_limiting.trust_proxy_headers,
        trusted_proxy_cidrs=settings.rate_limiting.trusted_proxy_cidrs,
        identifier_secret=identifier_secret,
    )

    await _check_rate_limit_for_identifier(
        request=request,
        policy=effective_policy,
        identifier=identifier,
        started_at=started_at,
    )


async def check_rate_limit(
    *,
    request: Request,
    principal: AuthenticatedPrincipal | None,
    policy: RateLimitPolicy | RateLimitPolicySpec,
) -> None:
    settings = _settings_from_request(request)

    if not settings.rate_limiting.enabled:
        return

    effective_policy = _effective_policy(request=request, policy=policy)
    started_at = time.perf_counter()
    identifier_secret = _identifier_secret_or_error(
        request=request,
        policy_name=effective_policy.name,
        started_at=started_at,
    )

    identifier = build_identifier(
        principal=principal,
        request=request,
        trust_proxy_headers=settings.rate_limiting.trust_proxy_headers,
        trusted_proxy_cidrs=settings.rate_limiting.trusted_proxy_cidrs,
        identifier_secret=identifier_secret,
    )

    await _check_rate_limit_for_identifier(
        request=request,
        policy=effective_policy,
        identifier=identifier,
        started_at=started_at,
    )


def rate_limit_dependency(
    policy: RateLimitPolicy | RateLimitPolicySpec,
) -> Callable[..., Awaitable[None]]:
    async def _dependency(
        request: Request,
        principal: Annotated[
            AuthenticatedPrincipal,
            Depends(require_authenticated_principal),
        ],
    ) -> None:
        await check_rate_limit(request=request, principal=principal, policy=policy)

    _dependency.__rate_limit_policy_name__ = policy.name  # type: ignore[attr-defined]
    _dependency.__rate_limit_policy__ = policy  # type: ignore[attr-defined]
    return _dependency

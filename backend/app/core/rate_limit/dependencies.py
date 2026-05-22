from __future__ import annotations

import asyncio
import math
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Annotated, Any

from fastapi import Depends, Request
from redis.exceptions import ConnectionError as RedisConnectionError
from redis.exceptions import RedisError
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
from app.core.rate_limit.grouped_atomic import (
    GroupedBucketSpec,
    atomic_consume_grouped_buckets,
    build_grouped_redis_key,
    is_redis_cross_slot_error,
    maybe_get_async_redis_client,
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

_RATE_LIMIT_BACKEND_ERRORS = (
    RedisConnectionError,
    RedisTimeoutError,
    RedisError,
    TimeoutError,
    RuntimeError,
)
_RATE_LIMIT_STATS_FALLBACK_ERRORS = (*_RATE_LIMIT_BACKEND_ERRORS, AttributeError)


@dataclass(frozen=True)
class _PreparedRateLimitCheck:
    policy: RateLimitPolicy
    identifier: RateLimitIdentifier
    namespace: str
    started_at: float


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


def _rate_limit_namespace(
    *,
    redis_prefix: str,
    policy: RateLimitPolicy,
    identifier: RateLimitIdentifier,
) -> str:
    return f"{redis_prefix}:{policy.name}:{identifier.kind}"


def _record_runtime_unavailable(
    *,
    policy_name: str,
    started_at: float,
) -> None:
    record_rate_limit_backend_error(
        policy_name=policy_name,
        identifier_kind="unknown",
        error_type="RuntimeUnavailable",
    )
    _record_rate_limit_outcome(
        policy_name=policy_name,
        result="runtime_unavailable",
        identifier_kind="unknown",
        started_at=started_at,
    )


def _raise_runtime_unavailable(
    *,
    policy_name: str,
    started_at: float,
    detail: str = "Rate limiter is unavailable.",
) -> None:
    _record_runtime_unavailable(policy_name=policy_name, started_at=started_at)
    raise RateLimiterUnavailableError(detail=detail)


async def _retry_after_for_identifier(
    *,
    request: Request,
    policy: RateLimitPolicy,
    namespace: str,
    identifier: RateLimitIdentifier,
) -> str:
    settings = _settings_from_request(request)
    try:
        window = await _await_with_timeout(
            _runtime_from_request(request).limiter.get_window_stats(
                policy.item,
                namespace,
                identifier.bucket_key,
            ),
            timeout_seconds=settings.rate_limiting.storage_timeout_seconds,
        )
        return _build_retry_after(window.reset_time)
    except _RATE_LIMIT_STATS_FALLBACK_ERRORS:
        return str(policy.item.get_expiry())


async def _raise_too_many_requests(
    *,
    request: Request,
    policy: RateLimitPolicy,
    namespace: str,
    identifier: RateLimitIdentifier,
) -> None:
    retry_after = await _retry_after_for_identifier(
        request=request,
        policy=policy,
        namespace=namespace,
        identifier=identifier,
    )
    raise TooManyRequestsError(
        detail="Too many requests.",
        headers={
            "Retry-After": retry_after,
            "Access-Control-Expose-Headers": "Retry-After",
        },
    )


async def _handle_rate_limit_backend_error(
    *,
    request: Request,
    policy: RateLimitPolicy,
    identifier: RateLimitIdentifier,
    started_at: float,
    exc: Exception,
) -> bool:
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
        return True

    _record_rate_limit_outcome(
        policy_name=policy.name,
        result="backend_error",
        identifier_kind=identifier.kind,
        started_at=started_at,
    )
    raise RateLimiterUnavailableError(
        detail="Rate limiter is temporarily unavailable.",
    ) from exc


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
        _raise_runtime_unavailable(
            policy_name=policy.name,
            started_at=started_at,
        )

    namespace = _rate_limit_namespace(
        redis_prefix=settings.rate_limiting.redis_prefix,
        policy=policy,
        identifier=identifier,
    )

    try:
        allowed = await _await_with_timeout(
            runtime.limiter.hit(policy.item, namespace, identifier.bucket_key),
            timeout_seconds=settings.rate_limiting.storage_timeout_seconds,
        )
    except _RATE_LIMIT_BACKEND_ERRORS as exc:
        if await _handle_rate_limit_backend_error(
            request=request,
            policy=policy,
            identifier=identifier,
            started_at=started_at,
            exc=exc,
        ):
            return
        raise  # pragma: no cover

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
    await _raise_too_many_requests(
        request=request,
        policy=policy,
        namespace=namespace,
        identifier=identifier,
    )


async def _test_rate_limit_for_identifier(
    *,
    request: Request,
    policy: RateLimitPolicy,
    identifier: RateLimitIdentifier,
    namespace: str,
    started_at: float,
) -> None:
    """Check a bucket without consuming quota.

    This is used for grouped business buckets so a later depleted bucket cannot
    burn earlier buckets before the request is denied. The production `limits`
    async strategies expose `test()`. Some lightweight test doubles may not; in
    that case we fall back to the historical behaviour for compatibility.
    """
    settings = _settings_from_request(request)
    runtime = _runtime_from_request(request)

    if runtime is None or runtime.limiter is None:
        _raise_runtime_unavailable(
            policy_name=policy.name,
            started_at=started_at,
        )

    test_method = getattr(runtime.limiter, "test", None)
    if not callable(test_method):
        return

    try:
        allowed = await _await_with_timeout(
            test_method(policy.item, namespace, identifier.bucket_key),
            timeout_seconds=settings.rate_limiting.storage_timeout_seconds,
        )
    except _RATE_LIMIT_BACKEND_ERRORS as exc:
        if await _handle_rate_limit_backend_error(
            request=request,
            policy=policy,
            identifier=identifier,
            started_at=started_at,
            exc=exc,
        ):
            return
        raise  # pragma: no cover

    if allowed:
        _record_rate_limit_outcome(
            policy_name=policy.name,
            result="preflight_allowed",
            identifier_kind=identifier.kind,
            started_at=started_at,
        )
        return

    _record_rate_limit_outcome(
        policy_name=policy.name,
        result="preflight_blocked",
        identifier_kind=identifier.kind,
        started_at=started_at,
    )
    await _raise_too_many_requests(
        request=request,
        policy=policy,
        namespace=namespace,
        identifier=identifier,
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


def _prepare_bucket_rate_limit_check(
    *,
    request: Request,
    bucket: RateLimitBucket,
    policy: RateLimitPolicy | RateLimitPolicySpec,
) -> _PreparedRateLimitCheck:
    settings = _settings_from_request(request)
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
    namespace = _rate_limit_namespace(
        redis_prefix=settings.rate_limiting.redis_prefix,
        policy=effective_policy,
        identifier=identifier,
    )
    return _PreparedRateLimitCheck(
        policy=effective_policy,
        identifier=identifier,
        namespace=namespace,
        started_at=started_at,
    )


async def check_rate_limit_for_bucket(
    *,
    request: Request,
    bucket: RateLimitBucket,
    policy: RateLimitPolicy | RateLimitPolicySpec,
) -> None:
    settings = _settings_from_request(request)

    if not settings.rate_limiting.enabled:
        return

    prepared = _prepare_bucket_rate_limit_check(
        request=request,
        bucket=bucket,
        policy=policy,
    )
    await _check_rate_limit_for_identifier(
        request=request,
        policy=prepared.policy,
        identifier=prepared.identifier,
        started_at=prepared.started_at,
    )


def _grouped_redis_client_from_runtime(runtime: Any | None) -> Any | None:
    if runtime is None:
        return None

    explicit_client = getattr(runtime, "grouped_redis_client", None)
    if explicit_client is not None:
        return explicit_client

    storage = getattr(runtime, "storage", None)
    if storage is None:
        return None
    return maybe_get_async_redis_client(storage)


def _strictest_prepared_check(
    prepared_checks: list[_PreparedRateLimitCheck],
) -> _PreparedRateLimitCheck:
    return min(prepared_checks, key=lambda prepared: prepared.policy.fail_open)


async def _check_grouped_rate_limits_with_compatibility_fallback(
    *,
    request: Request,
    prepared_checks: list[_PreparedRateLimitCheck],
) -> None:
    for prepared in prepared_checks:
        await _test_rate_limit_for_identifier(
            request=request,
            policy=prepared.policy,
            identifier=prepared.identifier,
            namespace=prepared.namespace,
            started_at=prepared.started_at,
        )

    for prepared in prepared_checks:
        await _check_rate_limit_for_identifier(
            request=request,
            policy=prepared.policy,
            identifier=prepared.identifier,
            started_at=prepared.started_at,
        )


async def check_rate_limits_for_buckets(
    *,
    request: Request,
    checks: list[tuple[RateLimitPolicy | RateLimitPolicySpec, RateLimitBucket]],
) -> None:
    settings = _settings_from_request(request)

    if not settings.rate_limiting.enabled:
        return
    if not checks:
        return

    prepared_checks = [
        _prepare_bucket_rate_limit_check(
            request=request,
            bucket=bucket,
            policy=policy,
        )
        for policy, bucket in checks
    ]

    redis_client = _grouped_redis_client_from_runtime(_runtime_from_request(request))

    if redis_client is not None:
        bucket_specs = [
            GroupedBucketSpec(
                key=build_grouped_redis_key(
                    namespace=prepared.namespace,
                    bucket_key=prepared.identifier.bucket_key,
                ),
                limit=prepared.policy.item.amount,
                expiry_seconds=prepared.policy.item.get_expiry(),
            )
            for prepared in prepared_checks
        ]
        try:
            grouped_result = await _await_with_timeout(
                atomic_consume_grouped_buckets(
                    redis_client=redis_client,
                    buckets=bucket_specs,
                ),
                timeout_seconds=settings.rate_limiting.storage_timeout_seconds,
            )
        except Exception as exc:
            if is_redis_cross_slot_error(exc):
                strictest = _strictest_prepared_check(prepared_checks)
                record_rate_limit_backend_error(
                    policy_name=strictest.policy.name,
                    identifier_kind=strictest.identifier.kind,
                    error_type=exc.__class__.__name__,
                )
                log.warning(
                    "rate_limiter_grouped_cross_slot_fallback",
                    policy=strictest.policy.name,
                    identifier_kind=strictest.identifier.kind,
                    reason=exc.__class__.__name__,
                    category="security",
                )
                await _check_grouped_rate_limits_with_compatibility_fallback(
                    request=request,
                    prepared_checks=prepared_checks,
                )
                return

            if isinstance(exc, _RATE_LIMIT_BACKEND_ERRORS):
                strictest = _strictest_prepared_check(prepared_checks)
                if await _handle_rate_limit_backend_error(
                    request=request,
                    policy=strictest.policy,
                    identifier=strictest.identifier,
                    started_at=strictest.started_at,
                    exc=exc,
                ):
                    return
            raise

        if grouped_result.allowed:
            for prepared in prepared_checks:
                _record_rate_limit_outcome(
                    policy_name=prepared.policy.name,
                    result="allowed",
                    identifier_kind=prepared.identifier.kind,
                    started_at=prepared.started_at,
                )
            return

        blocked = prepared_checks[grouped_result.blocked_index or 0]
        _record_rate_limit_outcome(
            policy_name=blocked.policy.name,
            result="blocked",
            identifier_kind=blocked.identifier.kind,
            started_at=blocked.started_at,
        )
        raise TooManyRequestsError(
            detail="Too many requests.",
            headers={
                "Retry-After": str(grouped_result.retry_after_seconds or 1),
                "Access-Control-Expose-Headers": "Retry-After",
            },
        )

    # Compatibility fallback for non-Redis runtimes and lightweight test doubles.
    await _check_grouped_rate_limits_with_compatibility_fallback(
        request=request,
        prepared_checks=prepared_checks,
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

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
from app.core.observability.metrics import (
    record_rate_limit_backend_error,
    record_rate_limit_check_duration,
    record_rate_limit_request,
)
from app.core.rate_limit.identifiers import build_identifier
from app.core.rate_limit.policies import RateLimitPolicy

log = get_logger(__name__)


async def _await_with_timeout(awaitable: Awaitable[Any], timeout_seconds: float) -> Any:
    return await asyncio.wait_for(awaitable, timeout=timeout_seconds)


def _runtime_from_request(request: Request) -> Any | None:
    return getattr(request.app.state, "rate_limiter_runtime", None)


def _build_retry_after(reset_time: float) -> str:
    retry_after = max(1, math.ceil(reset_time - time.time()))
    return str(retry_after)


def rate_limit_dependency(policy: RateLimitPolicy) -> Callable[..., Awaitable[None]]:
    async def _dependency(
        request: Request,
        principal: Annotated[
            AuthenticatedPrincipal,
            Depends(require_authenticated_principal),
        ],
    ) -> None:
        settings = get_settings()
        runtime = _runtime_from_request(request)

        if not settings.rate_limiting.enabled:
            return

        if runtime is None or runtime.limiter is None:
            raise RateLimiterUnavailableError(
                detail="Rate limiter is unavailable.",
            )

        identifier = build_identifier(
            principal=principal,
            request=request,
            trust_proxy_headers=settings.rate_limiting.trust_proxy_headers,
        )

        namespace = (
            f"{settings.rate_limiting.redis_prefix}:{policy.name}:{identifier.kind}"
        )
        item = policy.item
        started_at = time.perf_counter()

        try:
            allowed = await _await_with_timeout(
                runtime.limiter.hit(item, namespace, identifier.hashed_value),
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
                record_rate_limit_request(
                    policy_name=policy.name,
                    result="fail_open",
                    identifier_kind=identifier.kind,
                )
                record_rate_limit_check_duration(
                    policy_name=policy.name,
                    result="fail_open",
                    identifier_kind=identifier.kind,
                    duration_seconds=time.perf_counter() - started_at,
                )
                log.warning(
                    "rate_limiter_fail_open",
                    policy=policy.name,
                    identifier_kind=identifier.kind,
                    reason=exc.__class__.__name__,
                    category="security",
                )
                return

            record_rate_limit_request(
                policy_name=policy.name,
                result="backend_error",
                identifier_kind=identifier.kind,
            )
            record_rate_limit_check_duration(
                policy_name=policy.name,
                result="backend_error",
                identifier_kind=identifier.kind,
                duration_seconds=time.perf_counter() - started_at,
            )
            raise RateLimiterUnavailableError(
                detail="Rate limiter is temporarily unavailable.",
            ) from exc

        if allowed:
            record_rate_limit_request(
                policy_name=policy.name,
                result="allowed",
                identifier_kind=identifier.kind,
            )
            record_rate_limit_check_duration(
                policy_name=policy.name,
                result="allowed",
                identifier_kind=identifier.kind,
                duration_seconds=time.perf_counter() - started_at,
            )
            return

        record_rate_limit_request(
            policy_name=policy.name,
            result="blocked",
            identifier_kind=identifier.kind,
        )
        record_rate_limit_check_duration(
            policy_name=policy.name,
            result="blocked",
            identifier_kind=identifier.kind,
            duration_seconds=time.perf_counter() - started_at,
        )
        try:
            window = await _await_with_timeout(
                runtime.limiter.get_window_stats(
                    item,
                    namespace,
                    identifier.hashed_value,
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

    return _dependency

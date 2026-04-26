from __future__ import annotations

import asyncio
import math
import time
from collections.abc import Callable
from typing import Annotated

from fastapi import Depends, Request

from app.core.auth import AuthenticatedPrincipal, get_authenticated_principal
from app.core.config.settings import get_settings
from app.core.errors.exceptions import (
    RateLimiterUnavailableError,
    TooManyRequestsError,
)
from app.core.logging import get_logger
from app.core.rate_limit.identifiers import build_key_identifier
from app.core.rate_limit.policies import RateLimitPolicy
from app.core.rate_limit.state import RateLimitRuntime

PrincipalOptionalDep = Annotated[
    AuthenticatedPrincipal | None,
    Depends(get_authenticated_principal),
]


def _build_bucket_key(
    *,
    request: Request,
    policy: RateLimitPolicy,
    principal: AuthenticatedPrincipal | None,
) -> str:
    settings = get_settings().rate_limiting
    id_type, hashed_identifier = build_key_identifier(
        principal=principal,
        request=request,
        settings=settings,
    )
    return (
        f"{settings.redis_prefix}:{policy.name}:"
        f"{request.method.lower()}:{id_type}:{hashed_identifier}"
    )


async def _hit_with_timeout(
    runtime: RateLimitRuntime,
    policy: RateLimitPolicy,
    key: str,
):
    timeout_seconds = get_settings().rate_limiting.storage_timeout_seconds
    return await asyncio.wait_for(
        runtime.limiter.hit(policy.limit, key),
        timeout=timeout_seconds,
    )


async def _window_stats_with_timeout(
    runtime: RateLimitRuntime,
    policy: RateLimitPolicy,
    key: str,
):
    timeout_seconds = get_settings().rate_limiting.storage_timeout_seconds
    return await asyncio.wait_for(
        runtime.limiter.get_window_stats(policy.limit, key),
        timeout=timeout_seconds,
    )


def _normalize_retry_after(policy: RateLimitPolicy, reset_time: float | None) -> int:
    if reset_time is None:
        return policy.limit.get_expiry()

    return max(1, math.ceil(reset_time - time.time()))


def rate_limit_dependency(policy: RateLimitPolicy) -> Callable[..., None]:
    async def _dependency(
        request: Request,
        principal: PrincipalOptionalDep,
    ) -> None:
        settings = get_settings().rate_limiting
        if not settings.enabled:
            return

        runtime: RateLimitRuntime | None = getattr(
            request.app.state,
            "rate_limit_runtime",
            None,
        )
        if runtime is None:
            raise RateLimiterUnavailableError(detail="Rate limiter is unavailable")

        key = _build_bucket_key(request=request, policy=policy, principal=principal)
        logger = get_logger(__name__)

        try:
            allowed = await _hit_with_timeout(runtime, policy, key)
            if allowed:
                return

            window_stats = await _window_stats_with_timeout(runtime, policy, key)
            retry_after = _normalize_retry_after(policy, window_stats.reset_time)

            raise TooManyRequestsError(
                detail="Rate limit exceeded. Try again later.",
                extra={"retry_after": retry_after},
            )
        except TooManyRequestsError:
            raise
        except Exception as exc:
            if policy.fail_open:
                logger.warning(
                    "rate_limiter_unavailable_fail_open",
                    policy=policy.name,
                    error_type=exc.__class__.__name__,
                )
                return

            raise RateLimiterUnavailableError(
                detail="Rate limiter is unavailable"
            ) from exc

    return _dependency

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from redis.exceptions import ConnectionError as RedisConnectionError
from redis.exceptions import TimeoutError as RedisTimeoutError

if TYPE_CHECKING:
    from app.core.rate_limit.state import RateLimitRuntime


def is_rate_limiter_backend_error(exc: Exception) -> bool:
    if isinstance(exc, (RedisConnectionError, RedisTimeoutError, asyncio.TimeoutError)):
        return True

    storage_error_types: tuple[type[BaseException], ...] = ()
    if hasattr(exc, "__rate_limit_runtime"):
        runtime = getattr(exc, "__rate_limit_runtime")
        if isinstance(runtime, RateLimitRuntime):
            storage_error_types = runtime.storage_exceptions

    if storage_error_types and isinstance(exc, storage_error_types):
        return True

    return exc.__class__.__module__.startswith("limits")

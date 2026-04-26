from __future__ import annotations

from dataclasses import dataclass

from limits.aio.storage.base import Storage
from limits.aio.strategies import (
    FixedWindowRateLimiter,
    MovingWindowRateLimiter,
    SlidingWindowCounterRateLimiter,
)

RateLimiterStrategy = (
    MovingWindowRateLimiter | SlidingWindowCounterRateLimiter | FixedWindowRateLimiter
)


@dataclass(slots=True)
class RateLimitRuntime:
    storage: Storage
    limiter: RateLimiterStrategy
    strategy_name: str
    storage_exceptions: tuple[type[BaseException], ...]

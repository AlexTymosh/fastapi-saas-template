from __future__ import annotations

from fastapi import FastAPI
from limits.aio.storage import RedisStorage, storage_from_string
from limits.aio.strategies import (
    FixedWindowRateLimiter,
    MovingWindowRateLimiter,
    SlidingWindowCounterRateLimiter,
)

from app.core.config.settings import Settings
from app.core.logging import get_logger
from app.core.rate_limit.state import RateLimitRuntime


def _build_storage_uri(redis_url: str) -> str:
    if redis_url.startswith("redis://"):
        return "async+" + redis_url
    if redis_url.startswith("rediss://"):
        return "async+" + redis_url
    return redis_url


def _pick_limiter(storage: RedisStorage):
    try:
        limiter = MovingWindowRateLimiter(storage)
        return limiter, "moving-window"
    except NotImplementedError:
        pass

    try:
        limiter = SlidingWindowCounterRateLimiter(storage)
        return limiter, "sliding-window-counter"
    except NotImplementedError:
        limiter = FixedWindowRateLimiter(storage)
        return limiter, "fixed-window"


async def setup_rate_limiter(app: FastAPI, settings: Settings) -> None:
    logger = get_logger(__name__)
    app.state.rate_limit_runtime = None

    if not settings.rate_limiting.enabled:
        if settings.app.environment in {"staging", "prod"}:
            logger.warning(
                "rate_limiting_disabled_in_non_local_environment",
                environment=settings.app.environment,
            )
        return

    if settings.rate_limiting.backend != "redis":
        raise RuntimeError("RATE_LIMITING__BACKEND currently supports only redis")

    if not settings.redis.url:
        raise RuntimeError("REDIS__URL must be set when rate limiting is enabled")

    storage = storage_from_string(
        _build_storage_uri(settings.redis.url),
        implementation="redispy",
    )
    limiter, strategy_name = _pick_limiter(storage)

    app.state.rate_limit_runtime = RateLimitRuntime(
        storage=storage,
        limiter=limiter,
        strategy_name=strategy_name,
        storage_exceptions=tuple(getattr(storage, "base_exceptions", tuple())),
    )

    logger.info("rate_limiter_initialized", strategy=strategy_name)


async def teardown_rate_limiter(app: FastAPI) -> None:
    runtime: RateLimitRuntime | None = getattr(app.state, "rate_limit_runtime", None)
    if runtime is None:
        return

    close = getattr(runtime.storage, "close", None)
    if close is not None:
        await close()

    app.state.rate_limit_runtime = None

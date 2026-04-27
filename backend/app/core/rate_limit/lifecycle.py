from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from fastapi import FastAPI

from app.core.config.settings import Settings
from app.core.logging import get_logger


@dataclass
class RateLimiterRuntime:
    enabled: bool
    storage: Any | None
    limiter: Any | None
    strategy_name: str | None


def _build_async_redis_uri(redis_url: str) -> str:
    if redis_url.startswith("async+"):
        return redis_url
    return f"async+{redis_url}"


def _select_rate_limiter_strategy(storage: Any) -> tuple[Any, str]:
    from limits.aio.strategies import (  # type: ignore[import-not-found]
        FixedWindowRateLimiter,
        SlidingWindowCounterRateLimiter,
    )

    try:
        from limits.aio.strategies import (  # type: ignore[import-not-found]
            MovingWindowRateLimiter,
        )

        return MovingWindowRateLimiter(storage), "moving-window"
    except ImportError:
        pass

    try:
        return SlidingWindowCounterRateLimiter(storage), "sliding-window-counter"
    except Exception:
        return FixedWindowRateLimiter(storage), "fixed-window"


async def init_rate_limiter(app: FastAPI, settings: Settings) -> None:
    log = get_logger(__name__)
    environment = settings.app.environment

    if not settings.rate_limiting.enabled:
        secure_environment = environment in {"staging", "prod"}
        allow_disabled_in_prod = settings.rate_limiting.allow_disabled_in_prod

        if secure_environment and not allow_disabled_in_prod:
            raise RuntimeError(
                "RATE_LIMITING__ENABLED=false is not allowed in staging/prod unless "
                "RATE_LIMITING__ALLOW_DISABLED_IN_PROD=true"
            )

        app.state.rate_limiter_runtime = RateLimiterRuntime(
            enabled=False,
            storage=None,
            limiter=None,
            strategy_name=None,
        )
        if secure_environment and allow_disabled_in_prod:
            log.warning(
                "rate_limiting_disabled_in_secure_environment",
                environment=environment,
                category="security",
                allow_disabled_in_prod=True,
            )
        return

    redis_url = settings.redis.url
    if not redis_url:
        raise RuntimeError("REDIS__URL is required when RATE_LIMITING__ENABLED=true")

    from limits.storage import storage_from_string  # type: ignore[import-not-found]

    storage = storage_from_string(_build_async_redis_uri(redis_url))
    limiter, strategy_name = _select_rate_limiter_strategy(storage)

    app.state.rate_limiter_runtime = RateLimiterRuntime(
        enabled=True,
        storage=storage,
        limiter=limiter,
        strategy_name=strategy_name,
    )

    log.info(
        "rate_limiter_initialized",
        strategy=strategy_name,
        backend=settings.rate_limiting.backend,
        category="security",
    )


async def shutdown_rate_limiter(app: FastAPI) -> None:
    runtime = getattr(app.state, "rate_limiter_runtime", None)
    if runtime is None or runtime.storage is None:
        return

    close_method = getattr(runtime.storage, "aclose", None)
    if callable(close_method):
        await close_method()
        return

    close_method = getattr(runtime.storage, "close", None)
    if callable(close_method):
        maybe_awaitable = close_method()
        if hasattr(maybe_awaitable, "__await__"):
            await maybe_awaitable

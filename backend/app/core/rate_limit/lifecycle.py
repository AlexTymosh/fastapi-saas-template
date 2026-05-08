from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from fastapi import FastAPI

from app.core.config.settings import Settings
from app.core.logging import get_logger
from app.core.rate_limit.registry import build_effective_policy_registry


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


def _serialise_effective_policy(policy: Any) -> dict[str, Any]:
    return {
        "limit": policy.item.amount,
        "window_seconds": policy.item.get_expiry(),
        "fail_open": policy.fail_open,
        "sensitivity": policy.sensitivity,
        "override_applied": policy.override_applied,
    }


async def init_rate_limiter(app: FastAPI, settings: Settings) -> None:
    log = get_logger(__name__)
    policy_registry = build_effective_policy_registry(settings)
    app.state.rate_limit_policy_registry = policy_registry

    if not settings.rate_limiting.enabled:
        app.state.rate_limiter_runtime = RateLimiterRuntime(
            enabled=False,
            storage=None,
            limiter=None,
            strategy_name=None,
        )
        log.info(
            "rate_limit_policy_registry_resolved",
            mode=settings.rate_limiting.mode,
            enabled=False,
            policies={
                name: _serialise_effective_policy(policy)
                for name, policy in policy_registry.items()
            },
            category="security",
        )
        if settings.app.environment in {"staging", "prod"}:
            log.warning(
                "rate_limiting_disabled",
                environment=settings.app.environment,
                category="security",
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
        mode=settings.rate_limiting.mode,
        policies={
            name: _serialise_effective_policy(policy)
            for name, policy in policy_registry.items()
        },
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

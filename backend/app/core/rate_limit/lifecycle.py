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
    grouped_redis_client: Any | None = None


def _build_async_redis_uri(redis_url: str) -> str:
    if redis_url.startswith("async+"):
        return redis_url
    return f"async+{redis_url}"


def _build_grouped_redis_url(redis_url: str) -> str:
    """Return a redis-py compatible URL for the grouped Lua client.

    `limits` async storage accepts URLs prefixed with `async+redis://` or
    `async+rediss://`. The raw `redis.asyncio.Redis.from_url()` client does not
    understand that adapter prefix, so strip only the `async+` marker while
    preserving the underlying Redis scheme and all URL components.
    """

    if redis_url.startswith("async+"):
        return redis_url.removeprefix("async+")
    return redis_url


def _build_grouped_redis_client(redis_url: str) -> Any:
    """Create the explicit Redis client used by grouped Lua checks.

    The `limits` async Redis storage hides its backend behind bridge-specific
    internals (`coredis`, `redispy`, `valkey`). Grouped rate limits need a raw
    `EVAL` client, so keep that dependency explicit instead of relying on
    fragile introspection of the `limits` storage object.
    """

    from redis.asyncio import Redis

    return Redis.from_url(_build_grouped_redis_url(redis_url))


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


async def _close_maybe_async(resource: Any | None) -> None:
    if resource is None:
        return

    for method_name in ("aclose", "close"):
        close_method = getattr(resource, method_name, None)
        if not callable(close_method):
            continue
        maybe_awaitable = close_method()
        if hasattr(maybe_awaitable, "__await__"):
            await maybe_awaitable
        return


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
    grouped_redis_client = _build_grouped_redis_client(redis_url)

    app.state.rate_limiter_runtime = RateLimiterRuntime(
        enabled=True,
        storage=storage,
        limiter=limiter,
        strategy_name=strategy_name,
        grouped_redis_client=grouped_redis_client,
    )

    log.info(
        "rate_limiter_initialized",
        strategy=strategy_name,
        backend=settings.rate_limiting.backend,
        mode=settings.rate_limiting.mode,
        grouped_atomic_backend="redis_lua",
        policies={
            name: _serialise_effective_policy(policy)
            for name, policy in policy_registry.items()
        },
        category="security",
    )


async def shutdown_rate_limiter(app: FastAPI) -> None:
    runtime = getattr(app.state, "rate_limiter_runtime", None)
    if runtime is None:
        return

    await _close_maybe_async(getattr(runtime, "storage", None))
    await _close_maybe_async(getattr(runtime, "grouped_redis_client", None))

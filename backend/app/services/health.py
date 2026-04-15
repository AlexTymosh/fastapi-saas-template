import asyncio

from backend.app.schemas.health import HealthReadyResponse, ServiceStatus


async def _ping_postgresql() -> None:
    raise NotImplementedError("PostgreSQL check not implemented")


async def _ping_redis() -> None:
    raise NotImplementedError("Redis check not implemented")


async def check_postgresql(timeout: float = 1.0) -> bool:
    try:
        await asyncio.wait_for(_ping_postgresql(), timeout=timeout)
        return True
    except Exception:
        return False


async def check_redis(timeout: float = 0.5) -> bool:
    try:
        await asyncio.wait_for(_ping_redis(), timeout=timeout)
        return True
    except Exception:
        return False


async def get_readiness_status() -> HealthReadyResponse:
    pg_ok, redis_ok = await asyncio.gather(
        check_postgresql(),
        check_redis(),
    )

    checks: dict[str, bool] = {
        "postgresql": pg_ok,
        "redis": redis_ok,
    }

    services = {
        name: ServiceStatus.OK if ok else ServiceStatus.UNAVAILABLE
        for name, ok in checks.items()
    }

    all_ok = all(checks.values())

    return HealthReadyResponse(
        status=ServiceStatus.OK if all_ok else ServiceStatus.UNAVAILABLE,
        services=services,
    )

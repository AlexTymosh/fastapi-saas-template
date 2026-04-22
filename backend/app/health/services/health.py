import asyncio

from app.core.config.settings import get_settings
from app.core.db import ping_database
from app.core.logging import LogCategory, get_logger
from app.core.redis import ping_redis
from app.health.schemas.health import HealthReadyResponse, ServiceStatus

log = get_logger(__name__)


def _is_configured(value: str | None) -> bool:
    return bool(value and value.strip())


async def _ping_postgresql() -> None:
    await ping_database()


async def _ping_redis() -> None:
    await ping_redis()


async def check_postgresql(timeout: float | None = None) -> bool:
    effective_timeout = (
        timeout if timeout is not None else get_settings().database.healthcheck_timeout
    )

    try:
        await asyncio.wait_for(_ping_postgresql(), timeout=effective_timeout)
        return True
    except Exception as exc:
        log.warning(
            "postgresql_healthcheck_failed",
            category=LogCategory.APPLICATION,
            timeout=effective_timeout,
            error=str(exc),
            error_type=type(exc).__name__,
        )
        return False


async def check_redis(timeout: float | None = None) -> bool:
    effective_timeout = (
        timeout if timeout is not None else get_settings().redis.healthcheck_timeout
    )

    try:
        await asyncio.wait_for(_ping_redis(), timeout=effective_timeout)
        return True
    except Exception as exc:
        log.warning(
            "redis_healthcheck_failed",
            category=LogCategory.APPLICATION,
            timeout=effective_timeout,
            error=str(exc),
            error_type=type(exc).__name__,
        )
        return False


async def get_readiness_status() -> HealthReadyResponse:
    settings = get_settings()
    tasks: dict[str, asyncio.Task[bool]] = {}

    if _is_configured(settings.database.url):
        tasks["postgresql"] = asyncio.create_task(check_postgresql())

    if _is_configured(settings.redis.url):
        tasks["redis"] = asyncio.create_task(check_redis())

    checks = {name: await task for name, task in tasks.items()}

    services = {
        name: ServiceStatus.OK if ok else ServiceStatus.UNAVAILABLE
        for name, ok in checks.items()
    }

    all_ok = all(checks.values()) if checks else True
    result = HealthReadyResponse(
        status=ServiceStatus.OK if all_ok else ServiceStatus.UNAVAILABLE,
        services=services,
    )

    log.info(
        "readiness_checked",
        category=LogCategory.APPLICATION,
        status=result.status,
        services=result.services,
    )

    return result

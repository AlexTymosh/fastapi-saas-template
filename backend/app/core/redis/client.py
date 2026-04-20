from __future__ import annotations

from redis.asyncio import Redis
from redis.asyncio.connection import ConnectionPool

from app.core.config.settings import get_settings

_pool: ConnectionPool | None = None
_client: Redis | None = None
_redis_url: str | None = None


def _build_pool() -> ConnectionPool:
    settings = get_settings()
    redis_url = settings.redis.url
    if not redis_url:
        raise RuntimeError("REDIS__URL is not set")

    return ConnectionPool.from_url(
        redis_url,
        encoding="utf-8",
        decode_responses=True,
    )


def get_redis_client() -> Redis:
    global _pool, _client, _redis_url

    settings = get_settings()
    redis_url = settings.redis.url
    if not redis_url:
        raise RuntimeError("REDIS__URL is not set")

    if _client is None:
        _pool = _build_pool()
        _client = Redis(connection_pool=_pool)
        _redis_url = redis_url
        return _client

    if _redis_url != redis_url:
        raise RuntimeError(
            "Redis URL changed during runtime. "
            "Call close_redis() before reinitializing the client."
        )

    return _client


async def ping_redis() -> None:
    client = get_redis_client()
    ok = await client.ping()
    if ok is not True:
        raise RuntimeError("Redis ping returned unexpected response")


async def close_redis() -> None:
    global _pool, _client, _redis_url

    if _client is not None:
        await _client.aclose()

    if _pool is not None:
        await _pool.aclose()

    _client = None
    _pool = None
    _redis_url = None

from __future__ import annotations

import dramatiq
from dramatiq.brokers.redis import RedisBroker
from dramatiq.middleware import AsyncIO

from app.core.config.settings import get_settings


def configure_broker(*, require_redis: bool = False) -> RedisBroker | None:
    settings = get_settings()
    redis_url = settings.redis.url
    if not redis_url:
        if require_redis:
            raise RuntimeError(
                "REDIS__URL is required for Dramatiq runtime services "
                "(worker/dispatcher)."
            )
        return None

    broker = RedisBroker(url=redis_url)
    broker.add_middleware(AsyncIO())
    dramatiq.set_broker(broker)
    return broker


broker: RedisBroker | None = None

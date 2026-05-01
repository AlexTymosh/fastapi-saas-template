from __future__ import annotations

import dramatiq
from dramatiq.brokers.redis import RedisBroker
from dramatiq.middleware import AsyncIO

from app.core.config.settings import get_settings

_configured_broker: RedisBroker | None = None
broker: RedisBroker | None = None


def configure_broker(*, require_redis: bool = False) -> RedisBroker | None:
    """Configure Dramatiq broker with AsyncIO middleware.

    When Redis is not configured and `require_redis` is False, this function returns
    None to keep tests and import-time flows lightweight.
    """

    global _configured_broker, broker

    settings = get_settings()
    redis_url = settings.redis.url

    if not redis_url:
        if require_redis:
            raise RuntimeError(
                "REDIS__URL is required for worker/dispatcher runtime execution"
            )
        return None

    if _configured_broker is not None:
        broker = _configured_broker
        return _configured_broker

    new_broker = RedisBroker(url=redis_url)
    new_broker.add_middleware(AsyncIO())
    dramatiq.set_broker(new_broker)
    _configured_broker = new_broker
    broker = _configured_broker
    return _configured_broker

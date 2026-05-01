from __future__ import annotations

import dramatiq
from dramatiq.brokers.redis import RedisBroker

from app.core.config.settings import get_settings


def configure_broker() -> RedisBroker:
    settings = get_settings()
    redis_url = settings.redis.url
    if not redis_url:
        raise RuntimeError("REDIS__URL is required to start Dramatiq worker")
    broker = RedisBroker(url=redis_url)
    dramatiq.set_broker(broker)
    return broker


broker = configure_broker()

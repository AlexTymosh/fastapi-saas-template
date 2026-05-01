from __future__ import annotations

import dramatiq
from dramatiq.brokers.redis import RedisBroker

from app.core.config.settings import get_settings


def _build_broker() -> RedisBroker:
    settings = get_settings()
    redis_url = settings.redis.url
    if not redis_url:
        raise RuntimeError("REDIS__URL must be set for Dramatiq worker startup")
    return RedisBroker(url=redis_url)


broker = _build_broker()
dramatiq.set_broker(broker)

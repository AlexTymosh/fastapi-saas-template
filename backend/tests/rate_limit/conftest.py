from __future__ import annotations

from tests.fixtures.redis import (
    redis_cluster_integration_url as redis_cluster_integration_url,
)
from tests.fixtures.redis import redis_integration_url as redis_integration_url

__all__ = [
    "redis_cluster_integration_url",
    "redis_integration_url",
]
